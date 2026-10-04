"""/ask with a fake model: authentication, prompt, retry and error mapping."""

import json
import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.ask import (
    AskError,
    ChatResult,
    Example,
    OllamaClient,
    answer,
    build_messages,
    load_examples,
    select_examples,
    sign,
    verify_request,
)
from app.config import Settings
from app.main import create_app
from tests.test_api import ENV, fake_export, refresh

SECRET = "test-secret-3f9a"
USER_REF = "ab12cd34ef56"
GOOD_SQL = "```sql\nSELECT shortname FROM course ORDER BY shortname\n```"


class FakeModel:
    model = "fake-coder:1b"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.timeouts = []

    def chat(self, messages, timeout_s=None):
        self.calls.append([dict(m) for m in messages])
        self.timeouts.append(timeout_s)
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply()
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(content=reply, model_ms=5.0, prompt_eval_tokens=42)


@pytest.fixture
def settings(tmp_path):
    return Settings.from_env({**ENV, "DATA_DIR": str(tmp_path), "ASKDATA_SHARED_SECRET": SECRET, "MAX_ROWS": "50"})


def make_client(settings, model):
    app = create_app(settings, export_fn=fake_export, refresh_on_startup=False, chat_client=model)
    client = TestClient(app)
    r = refresh(client, secret=settings.askdata_secret)
    assert r.status_code == (200 if settings.askdata_secret else 503)
    return client


def signed(body, secret=SECRET, ts=None):
    raw = json.dumps(body).encode()
    ts = str(int(time.time()) if ts is None else ts)
    headers = {
        "Content-Type": "application/json",
        "X-Askdata-Timestamp": ts,
        "X-Askdata-Signature": sign(secret, ts, raw),
    }
    return raw, headers


def ask(client, body, **kw):
    raw, headers = signed(body, **kw)
    return client.post("/ask", content=raw, headers=headers)


BODY = {"question": "Which courses are there?", "course_ids": [2], "user_ref": USER_REF}


def test_signed_request_returns_rows_and_contract_fields(settings):
    model = FakeModel(GOOD_SQL)
    with make_client(settings, model) as client:
        r = ask(client, BODY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body)[:4] == ["sql", "columns", "rows", "elapsed_ms"]
    assert body["columns"] == ["shortname"]
    assert body["rows"] == [["C1"]]
    assert body["attempts"] == 1
    assert body["truncated"] is False
    assert body["model"] == "fake-coder:1b"
    assert body["sql"].startswith("SELECT shortname")
    assert set(body["timings"]) == {"model_ms", "sql_ms", "calls"}
    assert body["timings"]["calls"][0]["prompt_tokens"] == 42


def test_course_scope_comes_from_signed_course_ids(settings):
    model = FakeModel("```sql\nSELECT count(*) AS n FROM course\n```")
    with make_client(settings, model) as client:
        r = ask(client, {**BODY, "course_ids": [999]})
    assert r.json()["rows"] == [[0]]


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda h, raw: h.pop("X-Askdata-Signature"), "missing_auth"),
        (lambda h, raw: h.pop("X-Askdata-Timestamp"), "missing_auth"),
        (lambda h, raw: h.update({"X-Askdata-Signature": "0" * 64}), "bad_signature"),
        (lambda h, raw: h.update({"X-Askdata-Signature": sign("other", h["X-Askdata-Timestamp"], raw)}), "bad_signature"),
        (lambda h, raw: h.update({"X-Askdata-Timestamp": "12x"}), "bad_signature"),
    ],
)
def test_bad_auth_is_401(settings, mutate, reason):
    model = FakeModel(GOOD_SQL)
    with make_client(settings, model) as client:
        raw, headers = signed(BODY)
        mutate(headers, raw)
        r = client.post("/ask", content=raw, headers=headers)
    assert r.status_code == 401
    assert r.json()["detail"]["reason"] == reason
    assert model.calls == []


@pytest.mark.parametrize(
    "timestamp, signature",
    [
        ("\u00b2", "0" * 64),
        ("1" * 5000, "0" * 64),
        ("1700000000", "\u00e9" * 64),
        ("1700000000", "0" * 63),
        ("1700000000", "g" * 64),
        ("-1700000000", "0" * 64),
        ("1700000000.5", "0" * 64),
        ("\u0661\u0662", "0" * 64),
    ],
    ids=["superscript-two", "5000-digits", "non-ascii-signature", "short-signature", "non-hex", "negative", "decimal", "arabic-digits"],
)
def test_malformed_auth_headers_are_bad_signature(timestamp, signature):
    with pytest.raises(AskError) as err:
        verify_request(SECRET, timestamp, signature, b"{}", 300, now=1700000000)
    assert (err.value.status, err.value.reason) == (401, "bad_signature")


def test_signature_header_is_case_insensitive_hex():
    ts = "1700000000"
    verify_request(SECRET, ts, sign(SECRET, ts, b"{}").upper(), b"{}", 300, now=1700000000)


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Askdata-Timestamp": "\u00b2".encode(), "X-Askdata-Signature": b"0" * 64},
        {"X-Askdata-Timestamp": b"1" * 5000, "X-Askdata-Signature": b"0" * 64},
        {"X-Askdata-Timestamp": str(int(time.time())).encode(), "X-Askdata-Signature": "\u00e9".encode() * 32},
    ],
    ids=["superscript-two", "5000-digits", "non-ascii-signature"],
)
def test_malformed_auth_headers_over_http_are_401(settings, headers):
    model = FakeModel(GOOD_SQL)
    with make_client(settings, model) as client:
        r = client.post("/ask", content=json.dumps(BODY).encode(), headers={"Content-Type": "application/json", **headers})
    assert r.status_code == 401
    assert r.json()["detail"]["reason"] == "bad_signature"
    assert model.calls == []


def test_oversized_body_is_413_before_auth(settings):
    model = FakeModel(GOOD_SQL)
    with make_client(settings, model) as client:
        raw, headers = signed({**BODY, "question": "x" * 70_000})
        r = client.post("/ask", content=raw, headers=headers)
    assert r.status_code == 413
    assert r.json()["detail"]["reason"] == "too_large"
    assert model.calls == []


def test_oversized_chunked_body_is_413(settings):
    model = FakeModel(GOOD_SQL)
    with make_client(settings, model) as client:
        chunks = (b"x" * 16_384 for _ in range(5))
        r = client.post("/ask", content=chunks, headers={"X-Askdata-Timestamp": "1", "X-Askdata-Signature": "0" * 64})
    assert r.status_code == 413
    assert model.calls == []


def test_ask_is_503_busy_when_all_slots_are_taken(tmp_path):
    settings = Settings.from_env(
        {**ENV, "DATA_DIR": str(tmp_path), "ASKDATA_SHARED_SECRET": SECRET, "ASK_CONCURRENCY": "1"}
    )
    entered, release = threading.Event(), threading.Event()

    def slow():
        entered.set()
        release.wait(10)
        return GOOD_SQL

    model = FakeModel(slow, GOOD_SQL)
    with make_client(settings, model) as client:
        first = {}
        t = threading.Thread(target=lambda: first.update(r=ask(client, BODY)))
        t.start()
        assert entered.wait(10)
        busy = ask(client, BODY)
        release.set()
        t.join(10)
        after = ask(client, BODY)
    assert busy.status_code == 503
    assert busy.json()["detail"]["reason"] == "busy"
    assert busy.headers.get("retry-after")
    assert first["r"].status_code == 200
    assert after.status_code == 200
    assert len(model.calls) == 2


def test_ask_concurrency_setting():
    base = {**ENV, "ASKDATA_SHARED_SECRET": SECRET}
    assert Settings.from_env(base).ask_concurrency == 2
    assert Settings.from_env({**base, "ASK_CONCURRENCY": "4"}).ask_concurrency == 4
    with pytest.raises(ValueError):
        Settings.from_env({**base, "ASK_CONCURRENCY": "0"})


def test_ollama_timeout_defaults_to_150():
    assert Settings.from_env({**ENV}).ollama_timeout_s == 150


def test_signature_covers_the_raw_body(settings):
    model = FakeModel(GOOD_SQL)
    with make_client(settings, model) as client:
        raw, headers = signed(BODY)
        tampered = raw.replace(b"[2]", b"[2, 3]")
        r = client.post("/ask", content=tampered, headers=headers)
    assert r.status_code == 401
    assert r.json()["detail"]["reason"] == "bad_signature"


def test_expired_timestamp_is_401(settings):
    with make_client(settings, FakeModel(GOOD_SQL)) as client:
        r = ask(client, BODY, ts=int(time.time()) - 301)
        assert r.status_code == 401
        assert r.json()["detail"]["reason"] == "expired"
        assert ask(client, BODY, ts=int(time.time()) + 301).json()["detail"]["reason"] == "expired"


def test_replay_window_is_configurable(tmp_path):
    settings = Settings.from_env(
        {**ENV, "DATA_DIR": str(tmp_path), "ASKDATA_SHARED_SECRET": SECRET, "ASKDATA_REPLAY_WINDOW_S": "1000"}
    )
    with make_client(settings, FakeModel(GOOD_SQL)) as client:
        assert ask(client, BODY, ts=int(time.time()) - 900).status_code == 200


def test_no_secret_refuses_every_request(tmp_path):
    settings = Settings.from_env({**ENV, "DATA_DIR": str(tmp_path), "ASKDATA_SHARED_SECRET": ""})
    model = FakeModel(GOOD_SQL)
    with make_client(settings, model) as client:
        r = ask(client, BODY, secret="")
        assert r.status_code == 503
        assert r.json()["detail"]["reason"] == "not_configured"
        assert client.post("/ask", json=BODY).status_code == 503
    assert model.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "question": ""},
        {**BODY, "question": "x" * 2001},
        {**BODY, "course_ids": []},
        {**BODY, "course_ids": list(range(1, 202))},
        {**BODY, "course_ids": ["2"]},
        {**BODY, "user_ref": "not-hex!"},
        {**BODY, "user_ref": "abc"},
        {**BODY, "max_rows": 0},
        {"question": "x", "course_ids": [2]},
    ],
)
def test_invalid_body_is_422_after_auth(settings, body):
    model = FakeModel(GOOD_SQL)
    with make_client(settings, model) as client:
        r = ask(client, body)
    assert r.status_code == 422
    assert model.calls == []


def test_max_rows_is_clamped_to_the_server_limit(settings):
    sql = "```sql\nSELECT * FROM range(1000) AS t(i)\n```"
    with make_client(settings, FakeModel(sql, sql)) as client:
        small = ask(client, {**BODY, "max_rows": 3}).json()
        big = ask(client, {**BODY, "max_rows": 10_000}).json()
    assert len(small["rows"]) == 3 and small["truncated"] is True
    assert len(big["rows"]) == 50 and big["truncated"] is True


def test_not_truncated_when_rows_fit(settings):
    sql = "```sql\nSELECT * FROM range(50) AS t(i)\n```"
    with make_client(settings, FakeModel(sql)) as client:
        body = ask(client, BODY).json()
    assert len(body["rows"]) == 50 and body["truncated"] is False


def test_prompt_has_rules_schema_examples_and_question(settings):
    model = FakeModel(GOOD_SQL)
    question = "Which activity has the highest drop-off?"
    with make_client(settings, model) as client:
        ask(client, {**BODY, "question": question})
    messages = model.calls[0]
    system = messages[0]
    assert system["role"] == "system"
    assert "role = 'student'" in system["content"]
    assert "CREATE TABLE participant (" in system["content"]
    assert "days_since_last_login" in system["content"]
    assert "export_meta" not in system["content"]
    assert messages[-1] == {"role": "user", "content": question}
    shots = [m for m in messages[1:-1]]
    assert len(shots) == 2 * settings.examples_top_k
    assert shots[-1]["role"] == "assistant" and "lag(" in shots[-1]["content"]


def test_system_prompt_is_identical_across_questions(settings):
    model = FakeModel(GOOD_SQL, GOOD_SQL)
    with make_client(settings, model) as client:
        ask(client, {**BODY, "question": "Which students have not logged in for 14 days?"})
        ask(client, {**BODY, "question": "Average grade per item?"})
    assert model.calls[0][0] == model.calls[1][0]
    assert model.calls[0][1:] != model.calls[1][1:]


def test_drop_off_question_selects_drop_off_example():
    examples = load_examples()
    picked = select_examples("Where do students drop off the most along the course path?", examples, 6)
    assert picked[0].id == "drop_off"
    assert "drop-off" in picked[0].tags


def test_select_examples_is_stable_and_bounded():
    examples = [Example(id=str(i), question=f"question {i}", sql="SELECT 1") for i in range(10)]
    assert select_examples("anything", examples, 0) == []
    assert [e.id for e in select_examples("unrelated words", examples, 3)] == ["0", "1", "2"]


def test_build_messages_puts_best_example_last():
    a = Example(id="a", question="qa", sql="SELECT 1")
    b = Example(id="b", question="qb", sql="SELECT 2")
    messages = build_messages("CREATE TABLE t ();", [a, b], "q?")
    assert [m["content"] for m in messages[1:5]] == ["qb", "```sql\nSELECT 2\n```", "qa", "```sql\nSELECT 1\n```"]


def test_retry_after_guard_rejection(settings):
    model = FakeModel("```sql\nSELECT * FROM mdl_user\n```", GOOD_SQL)
    with make_client(settings, model) as client:
        r = ask(client, BODY)
    assert r.status_code == 200
    assert r.json()["attempts"] == 2
    retry = model.calls[1]
    assert retry[-2] == {"role": "assistant", "content": "```sql\nSELECT * FROM mdl_user\n```"}
    assert "SELECT * FROM mdl_user" in retry[-1]["content"]
    assert "Fix the SQL. Error: table 'mdl_user' is not available" in retry[-1]["content"]
    assert retry[0] == model.calls[0][0]


def test_retry_after_execution_error(settings):
    model = FakeModel("```sql\nSELECT nope FROM course\n```", GOOD_SQL)
    with make_client(settings, model) as client:
        r = ask(client, BODY)
    assert r.json()["attempts"] == 2
    assert "nope" in model.calls[1][-1]["content"]


def test_double_guard_failure_is_422_sql_rejected(settings):
    bad = "```sql\nDELETE FROM course\n```"
    with make_client(settings, FakeModel(bad, bad)) as client:
        r = ask(client, BODY)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["reason"] == "sql_rejected"
    assert "only SELECT" in detail["message"]
    assert detail["sql"] == "DELETE FROM course"


def test_double_execution_failure_is_422_sql_error_without_trace(settings):
    bad = "```sql\nSELECT nope FROM course\n```"
    with make_client(settings, FakeModel(bad, bad)) as client:
        r = ask(client, BODY)
    detail = r.json()["detail"]
    assert r.status_code == 422 and detail["reason"] == "sql_error"
    assert "nope" in detail["message"]
    assert "Traceback" not in r.text and "LINE" not in detail["message"]


def test_error_fed_back_to_the_model_is_truncated(settings):
    long_name = "n" * 2000
    model = FakeModel(f"```sql\nSELECT {long_name} FROM course\n```", GOOD_SQL)
    with make_client(settings, model) as client:
        r = ask(client, BODY)
    assert r.status_code == 200
    retry = model.calls[1][-1]["content"]
    error = retry.split("Error: ", 1)[1].split("\nReply with", 1)[0]
    assert len(error) <= 300
    assert error.endswith("...")


def _slow_bad_reply(now, seconds):
    def reply():
        now[0] += seconds
        return "```sql\nSELECT nope FROM course\n```"

    return reply


def test_model_calls_share_one_time_budget(settings):
    now = [0.0]
    model = FakeModel(_slow_bad_reply(now, 40), GOOD_SQL)
    with make_client(settings, FakeModel()) as client:
        db_path = str(client.app.state.settings.db_path)
    answer(BODY["question"], [2], 10, db_path, model, [], 0, 5, model_budget_s=150, clock=lambda: now[0])
    assert model.timeouts == [150, 110]


def test_exhausted_budget_is_504_without_a_second_call(settings):
    now = [0.0]
    model = FakeModel(_slow_bad_reply(now, 200), GOOD_SQL)
    with make_client(settings, FakeModel()) as client:
        db_path = str(client.app.state.settings.db_path)
    with pytest.raises(AskError) as err:
        answer(BODY["question"], [2], 10, db_path, model, [], 0, 5, model_budget_s=150, clock=lambda: now[0])
    assert (err.value.status, err.value.reason) == (504, "timeout")
    assert len(model.calls) == 1


def test_model_unavailable_is_502(settings):
    model = FakeModel(AskError(502, "model_unavailable", "Ollama is not reachable at http://x"))
    with make_client(settings, model) as client:
        r = ask(client, BODY)
    assert r.status_code == 502
    assert r.json()["detail"]["reason"] == "model_unavailable"


def test_model_timeout_is_504(settings):
    with make_client(settings, FakeModel(AskError(504, "timeout", "slow"))) as client:
        r = ask(client, BODY)
    assert r.status_code == 504 and r.json()["detail"]["reason"] == "timeout"


def test_real_client_maps_connection_refused_to_502():
    client = OllamaClient("http://127.0.0.1:9", "m", 2048, "1m", 2)
    with pytest.raises(AskError) as err:
        client.chat([{"role": "user", "content": "hi"}])
    assert err.value.status == 502 and err.value.reason == "model_unavailable"


def test_log_line_has_no_question_at_info(settings, caplog):
    secret_question = "Which students failed the secret exam?"
    with make_client(settings, FakeModel(GOOD_SQL)) as client, caplog.at_level(logging.INFO, logger="analytics.ask"):
        ask(client, {**BODY, "question": secret_question})
    lines = [r.getMessage() for r in caplog.records if r.name == "analytics.ask"]
    assert len(lines) == 1
    assert f"user_ref={USER_REF}" in lines[0] and "courses=1" in lines[0]
    assert "attempts=1" in lines[0] and "outcome=ok" in lines[0]
    assert secret_question not in lines[0]
