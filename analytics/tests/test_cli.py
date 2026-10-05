"""CLI helpers and the benchmark fact checkers."""

import hashlib
import hmac

from app.ask import sign
from app.cli import CLI_USER_REF, render_markdown, text_table
from app.demo_facts import check_courses, check_drop_off, check_grades, check_not_logged_in, check_not_submitted

SCOPE = ["DA101", "PROG101", "STAT201"]


def test_sign_matches_the_documented_contract():
    body = b'{"question": "q"}'
    expected = hmac.new(b"k", b"POST\n/ask\n1700000000\n" + body, hashlib.sha256).hexdigest()
    assert sign("k", "post", "/ask", 1700000000, body) == expected


def test_cli_user_ref_is_valid_hex():
    assert len(CLI_USER_REF) == 16 and int(CLI_USER_REF, 16) >= 0


def test_text_table_truncates_rows():
    out = text_table(["a", "b"], [[i, None] for i in range(3)], limit=2)
    assert out.splitlines()[0].startswith("a")
    assert "NULL" in out and "1 more rows" in out


def test_checkers_accept_lists_and_counts():
    assert check_courses([], [["DA101", "x", 95], ["PROG101", "y", 85], ["STAT201", "z", 75]], SCOPE)
    assert not check_courses([], [["DA101", "x", 95], ["PROG101", "y", 85]], SCOPE)
    refs = [f"{i:032x}" for i in range(25)]
    assert check_not_logged_in([], [["DA101", r] for r in refs], SCOPE)
    assert check_not_logged_in([], [["DA101", 23], ["PROG101", 20], ["STAT201", 25]], SCOPE)
    assert check_not_submitted([], [["DA101", 28], ["PROG101", 32], ["STAT201", 41]], SCOPE)
    assert not check_not_submitted([], [["DA101", 28], ["PROG101", 31], ["STAT201", 41]], SCOPE)
    assert check_not_submitted([], [[f"{i:032x}"] for i in range(101)], SCOPE)


def test_grade_and_drop_off_checkers():
    rows = [
        [c, item, avg]
        for c, items in {
            "DA101": {"Problem Set 1": 72.5, "Checkpoint quiz": 80.7},
            "PROG101": {"Problem Set 1": 66.6, "Checkpoint quiz": 74.1},
            "STAT201": {"Problem Set 1": 52.2, "Checkpoint quiz": 67.6},
        }.items()
        for item, avg in items.items()
    ]
    assert check_grades([], rows, SCOPE)
    assert not check_grades([], rows[:-1], SCOPE)
    assert check_drop_off([], [["STAT201", "Unit 2: Regression modelling", 70.6]], SCOPE)
    assert not check_drop_off([], [["DB201", "Introduce yourself", 10.0]], SCOPE)


def test_markdown_report_mentions_model_and_limits():
    results = [{
        "question": "Q | pipe", "status": 200, "elapsed_ms": 10, "model_ms": 8, "sql_ms": 1,
        "attempts": 1, "rows": 3, "sql": "SELECT 1", "correct": True,
    }]
    text = render_markdown("m:1b", [2, 3, 4], results, {"elapsed_ms": 5})
    assert "`m:1b`" in text and "Q \\| pipe" in text and "Known limits" in text
