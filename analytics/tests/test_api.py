import threading

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.export import ExportResult, build_database
from app.main import create_app
from tests.fake_moodle import NOW, attach_fake_moodle

ENV = {"ANALYTICS_DB_USER": "ro", "ANALYTICS_DB_PASSWORD": "pw", "ANALYTICS_SALT": "s", "REFRESH_MINUTES": "0"}


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

        r = client.post("/refresh")
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
        client.app.state.runner.wait_idle(timeout=10)
        assert client.get("/health").status_code == 200


def test_schema_returns_comments_and_prompt_text(settings):
    with TestClient(create_app(settings, export_fn=fake_export, refresh_on_startup=False)) as client:
        assert client.get("/schema").status_code == 503
        client.post("/refresh")
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
        t = threading.Thread(target=lambda: first.update(r=client.post("/refresh")))
        t.start()
        assert started.wait(10)
        second = client.post("/refresh")
        release.set()
        t.join(10)
        assert second.status_code == 409
        assert first["r"].status_code == 200


def test_refresh_failure_is_500_without_details(settings):
    def broken(s):
        raise RuntimeError("password=pw leaked")

    with TestClient(create_app(settings, export_fn=broken, refresh_on_startup=False)) as client:
        r = client.post("/refresh")
        assert r.status_code == 500
        assert "pw" not in r.text

