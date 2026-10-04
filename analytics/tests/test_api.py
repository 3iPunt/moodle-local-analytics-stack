import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.ask import sign
from app.config import Settings
from app.export import ExportError, ExportResult, build_database
from app.main import ExportRunner, create_app
from tests.fake_moodle import NOW, attach_fake_moodle

API_SECRET = "api-secret-71c2"
ENV = {
    "ANALYTICS_DB_USER": "ro",
    "ANALYTICS_DB_PASSWORD": "pw",
    "ANALYTICS_SALT": "s",
    "REFRESH_MINUTES": "0",
    "ASKDATA_SHARED_SECRET": API_SECRET,
}


def refresh(client, secret=API_SECRET, body=b""):
    ts = str(int(time.time()))
    headers = {"X-Askdata-Timestamp": ts, "X-Askdata-Signature": sign(secret, ts, body)}
    return client.post("/refresh", content=body, headers=headers)


def fake_export(settings):
    counts = build_database(settings.db_path, attach_fake_moodle, settings.salt, NOW, "mysql")
    return ExportResult(row_counts=counts, duration_ms=1.0, exported_at="2026-09-21T13:46:40", source="mysql")


@pytest.fixture
def settings(tmp_path):
    return Settings.from_env({**ENV, "DATA_DIR": str(tmp_path)})


def test_health_is_503_without_export_then_ok(settings):
    with TestClient(create_app(settings, export_fn=fake_export, refresh_on_startup=False)) as client:
        r = client.get("/health")
        assert r.status_code == 503
        assert r.json()["db_file"] is False

        r = refresh(client)
        assert r.status_code == 200
        assert r.json()["row_counts"]["course"] == 2

        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and body["db_file"] is True
        assert body["source"] == "mysql"
        assert body["row_counts"]["participant"] == 4
        assert body["last_export"].startswith("2026-09-21")


def test_startup_refresh_when_file_missing(settings):
    with TestClient(create_app(settings, export_fn=fake_export)) as client:
        assert client.app.state.runner.ready.wait(10)
        assert client.get("/health").status_code == 200


def test_startup_export_runs_even_when_file_exists(settings):
    fake_export(settings)
    calls = []

    def counting(s):
        calls.append(1)
        return fake_export(s)

    with TestClient(create_app(settings, export_fn=counting)) as client:
        assert client.app.state.runner.ready.wait(10)
    assert calls == [1]


def test_refresh_requires_a_signature(settings):
    with TestClient(create_app(settings, export_fn=fake_export, refresh_on_startup=False)) as client:
        assert client.post("/refresh").status_code == 401
        assert refresh(client, secret="wrong").status_code == 401
        assert client.get("/health").status_code == 503
        assert refresh(client).status_code == 200
        assert refresh(client, body=b"{}").status_code == 200


def test_startup_retry_backs_off_until_first_success(settings):
    outcomes = [ExportError("db down")] * 7 + [None]
    waits = []

    def flaky(s):
        outcome = outcomes.pop(0)
        if outcome:
            raise outcome
        return fake_export(s)

    def fake_wait(seconds):
        waits.append(seconds)
        return False

    runner = ExportRunner(settings, flaky)
    assert runner.run_until_success(threading.Event(), wait=fake_wait) == 8
    assert waits == [5, 10, 20, 40, 60, 60, 60]
    assert runner.ready.is_set()


def test_startup_retry_stops_on_shutdown(settings):
    def broken(s):
        raise ExportError("db down")

    stop = threading.Event()
    runner = ExportRunner(settings, broken)
    assert runner.run_until_success(stop, wait=lambda seconds: True) == 1
    assert not runner.ready.is_set()


def test_schema_returns_comments_and_prompt_text(settings):
    with TestClient(create_app(settings, export_fn=fake_export, refresh_on_startup=False)) as client:
        assert client.get("/schema").status_code == 503
        refresh(client)
        body = client.get("/schema").json()
        course = next(t for t in body["tables"] if t["name"] == "course")
        assert "course_id" in course["comment"]
        assert all(c["comment"] for c in course["columns"])
        assert "CREATE TABLE participant (" in body["prompt"]
        text = client.get("/schema", params={"format": "text"})
        assert text.headers["content-type"].startswith("text/plain")
        assert text.text == body["prompt"]


def test_concurrent_refresh_returns_409(settings):
    started, release = threading.Event(), threading.Event()

    def slow_export(s):
        started.set()
        release.wait(10)
        return fake_export(s)

    with TestClient(create_app(settings, export_fn=slow_export, refresh_on_startup=False)) as client:
        first = {}
        t = threading.Thread(target=lambda: first.update(r=refresh(client)))
        t.start()
        assert started.wait(10)
        second = refresh(client)
        release.set()
        t.join(10)
        assert second.status_code == 409
        assert first["r"].status_code == 200


def test_refresh_failure_is_500_without_details(settings):
    def broken(s):
        raise RuntimeError("password=pw leaked")

    with TestClient(create_app(settings, export_fn=broken, refresh_on_startup=False)) as client:
        r = refresh(client)
        assert r.status_code == 500
        assert "pw" not in r.text

