"""Every few-shot example passes the guard and answers on a demo export.

The export is built in a temporary directory "as of" ``DEMO_NOW_EPOCH`` (the
generation time of the demo data, passed by ``make test``) so the facts from
docs/demo-data.md hold however old the data is. Skipped without it or without
a reachable MySQL.
"""

import os

import pytest

from app.ask import load_examples
from app.db import open_query_connection, run_guarded
from app.demo_facts import DEMO_QUESTIONS, scope_names
from app.export import export
from app.schema import QUERY_TABLES
from tests.test_integration import _mysql, _settings, demo_now_epoch

pytestmark = pytest.mark.integration

ALL_COURSES = [2, 3, 4, 5, 6]
EXAMPLES = load_examples()
BY_ID = {e.id: e for e in EXAMPLES}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    if not os.environ.get("ANALYTICS_DB_USER"):
        pytest.skip("integration environment not configured")
    now = demo_now_epoch()
    settings = _settings(tmp_path_factory.mktemp("examples"), "duckdb")
    try:
        _mysql(settings).close()
    except Exception as err:  # noqa: BLE001
        pytest.skip(f"MySQL not reachable: {type(err).__name__}")
    if export(settings, now_epoch=now).row_counts["course"] == 0:
        pytest.skip("Moodle has no courses yet; run `make demo-data`")
    return str(settings.db_path)


@pytest.fixture(scope="module")
def con(db):
    c = open_query_connection(db, ALL_COURSES, QUERY_TABLES)
    yield c
    c.close()


def run(con, example_id):
    columns, rows, _ = run_guarded(con, BY_ID[example_id].sql, set(QUERY_TABLES), 500)
    return columns, rows


def test_example_file_shape():
    assert 15 <= len(EXAMPLES) <= 20
    assert len(BY_ID) == len(EXAMPLES)
    assert {q.example_id for q in DEMO_QUESTIONS} <= set(BY_ID)
    for q in DEMO_QUESTIONS:
        assert BY_ID[q.example_id].question == q.question


@pytest.mark.parametrize("example", EXAMPLES, ids=[e.id for e in EXAMPLES])
def test_example_runs_and_returns_rows(con, example):
    _, rows = run(con, example.id)
    assert rows


@pytest.mark.parametrize("demo", DEMO_QUESTIONS, ids=[q.example_id for q in DEMO_QUESTIONS])
def test_canonical_example_states_the_documented_facts(con, demo):
    columns, rows = run(con, demo.example_id)
    assert demo.check(columns, rows, scope_names(ALL_COURSES))


def test_drop_off_is_stat201_unit_2(con):
    columns, rows = run(con, "drop_off")
    top = dict(zip(columns, rows[0]))
    assert (top["shortname"], top["activity"], top["drop_pct"]) == ("STAT201", "Unit 2: Regression modelling", 70.6)


def test_not_logged_in_is_25_distinct_students(con):
    columns, rows = run(con, "not_logged_in_14")
    user = columns.index("user_ref")
    assert len({r[user] for r in rows}) == 25


def test_not_submitted_per_course(con):
    columns, rows = run(con, "not_submitted_this_week")
    counts = {}
    for row in rows:
        counts[row[0]] = counts.get(row[0], 0) + 1
    assert counts == {"DA101": 28, "PROG101": 32, "STAT201": 41, "RM301": 28, "DB201": 27}


def test_completion_ranking(con):
    _, rows = run(con, "compare_completion")
    assert [r[0] for r in rows] == ["DA101", "PROG101", "RM301", "DB201", "STAT201"]


def test_teacher_scope_limits_rows(db):
    c = open_query_connection(db, [2, 3, 4], QUERY_TABLES)
    try:
        _, rows, _ = run_guarded(c, BY_ID["courses_students"].sql, set(QUERY_TABLES), 500)
    finally:
        c.close()
    assert [(r[0], r[2]) for r in rows] == [("DA101", 95), ("PROG101", 85), ("STAT201", 75)]
