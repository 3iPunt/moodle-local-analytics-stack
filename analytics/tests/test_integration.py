"""Export the running stack's Moodle and check the facts in docs/demo-data.md.

Run inside the analytics container (``make test``) right after ``make demo-data``:
days_since_last_access is relative to the export time, so the inactivity
numbers drift once the demo data is several days old.
"""

import os

import duckdb
import pytest

from app.config import Settings
from app.export import TABLES, export, user_ref
from app.schema import describe_schema

pytestmark = pytest.mark.integration

PII_COLUMNS = {"firstname", "lastname", "email", "username", "ip", "lastip", "password"}
STUDENTS = {"DA101": 95, "PROG101": 85, "STAT201": 75, "RM301": 70, "DB201": 60}


def _settings(tmp_path, export_format):
    env = {**os.environ, "DATA_DIR": str(tmp_path), "EXPORT_FORMAT": export_format}
    return Settings.from_env(env)


def _mysql(settings):
    import pymysql

    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        connect_timeout=3,
    )


@pytest.fixture(scope="session")
def exports(tmp_path_factory):
    if not os.environ.get("ANALYTICS_DB_USER"):
        pytest.skip("integration environment not configured")
    duck = _settings(tmp_path_factory.mktemp("duckdb"), "duckdb")
    try:
        _mysql(duck).close()
    except Exception as err:  # noqa: BLE001
        pytest.skip(f"MySQL not reachable: {type(err).__name__}")
    parquet = _settings(tmp_path_factory.mktemp("parquet"), "parquet")
    return {"duckdb": (duck, export(duck)), "parquet": (parquet, export(parquet))}


@pytest.fixture(scope="session")
def con(exports):
    settings, _ = exports["duckdb"]
    c = duckdb.connect(str(settings.db_path), read_only=True)
    yield c
    c.close()


def per_course(con, sql):
    return dict(con.execute(sql).fetchall())


STUDENT_JOIN = "FROM base.participant AS p JOIN base.course AS c USING (course_id) WHERE p.role = 'student'"


def test_five_courses_and_students_per_course(con):
    assert con.execute("SELECT count(*) FROM base.course").fetchone()[0] == 5
    assert per_course(con, f"SELECT c.shortname, count(*) {STUDENT_JOIN} GROUP BY 1") == STUDENTS
    assert con.execute("SELECT count(DISTINCT user_ref) FROM base.participant WHERE role = 'student'").fetchone()[0] == 100


def test_teacher_courses(con, exports):
    settings, _ = exports["duckdb"]
    with _mysql(settings) as db, db.cursor() as cur:
        cur.execute("SELECT username, id FROM mdl_user WHERE username IN ('lmartinez', 'jokafor', 'schen')")
        ids = dict(cur.fetchall())
    expected = {
        "lmartinez": {"DA101", "PROG101", "STAT201"},
        "jokafor": {"STAT201", "RM301", "DB201"},
        "schen": {"PROG101"},
    }
    for username, courses in expected.items():
        ref = user_ref(ids[username], settings.salt)
        got = con.execute(
            "SELECT c.shortname FROM base.participant AS p JOIN base.course AS c USING (course_id) "
            "WHERE p.user_ref = ? AND p.role = 'editingteacher'",
            [ref],
        ).fetchall()
        assert {r[0] for r in got} == courses, username


def test_students_not_logged_in_for_14_days(con):
    got = per_course(
        con,
        "SELECT c.shortname, [count(*) FILTER (WHERE p.days_since_last_login IS NULL), "
        f"count(*) FILTER (WHERE p.days_since_last_login > 14)] {STUDENT_JOIN} GROUP BY 1",
    )
    assert got == {"DA101": [5, 18], "PROG101": [3, 17], "STAT201": [5, 20], "RM301": [4, 12], "DB201": [4, 7]}
    distinct = con.execute(
        "SELECT count(DISTINCT user_ref) FROM base.participant WHERE role = 'student' "
        "AND (days_since_last_login > 14 OR days_since_last_login IS NULL)"
    ).fetchone()[0]
    assert distinct == 25


def test_course_access_is_per_course(con):
    never = con.execute(
        "SELECT count(DISTINCT user_ref) FROM base.participant WHERE role = 'student' AND last_access_at IS NULL"
    ).fetchone()[0]
    assert never == 5
    stale_course_only = con.execute(
        "SELECT count(*) FROM base.participant WHERE role = 'student' "
        "AND days_since_last_access > 14 AND days_since_last_login <= 14"
    ).fetchone()[0]
    assert stale_course_only >= 1


def test_final_project_not_submitted(con):
    got = per_course(
        con,
        f"""
        SELECT c.shortname, count(*) {STUDENT_JOIN}
        AND NOT EXISTS (
            SELECT 1 FROM base.assignment_submission AS s JOIN base.activity AS a USING (cm_id)
            WHERE a.name = 'Final Project' AND s.course_id = p.course_id AND s.user_ref = p.user_ref
              AND s.status = 'submitted' AND s.latest
        )
        GROUP BY 1
        """,
    )
    assert got == {"DA101": 28, "PROG101": 32, "STAT201": 41, "RM301": 28, "DB201": 27}
    due = con.execute("SELECT count(*) FROM base.activity WHERE name = 'Final Project' AND due_at IS NOT NULL").fetchone()[0]
    assert due == 5


def test_stat201_completion_cliff(con):
    rates = con.execute(
        """
        WITH students AS (
            SELECT p.course_id, p.user_ref FROM base.participant AS p JOIN base.course AS c USING (course_id)
            WHERE p.role = 'student' AND c.shortname = 'STAT201'
        )
        SELECT round(100.0 * count(DISTINCT cp.user_ref) / (SELECT count(*) FROM students), 1)
        FROM base.activity AS a
        JOIN base.course AS c USING (course_id)
        LEFT JOIN base.completion AS cp
            ON cp.cm_id = a.cm_id AND cp.completed AND cp.user_ref IN (SELECT user_ref FROM students)
        WHERE c.shortname = 'STAT201' AND a.completion_tracked
        GROUP BY a.section, a.cm_id
        ORDER BY a.section, a.cm_id
        """
    ).fetchall()
    assert [r[0] for r in rates] == [93.3, 90.7, 89.3, 86.7, 85.3, 14.7, 12.0, 10.7]


def test_course_completion_ranking(con):
    rows = con.execute(
        """
        SELECT c.shortname, count(*) FILTER (WHERE cc.completed)
        FROM base.course AS c LEFT JOIN base.course_completion AS cc USING (course_id)
        GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()
    assert rows == [("DA101", 67), ("PROG101", 47), ("RM301", 28), ("DB201", 15), ("STAT201", 8)]


def test_grade_averages(con):
    got = con.execute(
        """
        SELECT c.shortname, gi.item_name, count(*), round(avg(g.final_grade), 1)
        FROM base.grade AS g JOIN base.grade_item AS gi USING (grade_item_id) JOIN base.course AS c ON c.course_id = g.course_id
        WHERE gi.item_type = 'mod'
        GROUP BY 1, 2
        """
    ).fetchall()
    assert {(r[0], r[1]): (r[2], r[3]) for r in got} == {
        ("DA101", "Problem Set 1"): (81, 72.5), ("DA101", "Checkpoint quiz"): (72, 80.7),
        ("PROG101", "Problem Set 1"): (64, 66.6), ("PROG101", "Checkpoint quiz"): (53, 74.1),
        ("STAT201", "Problem Set 1"): (64, 52.2), ("STAT201", "Checkpoint quiz"): (9, 67.6),
        ("RM301", "Problem Set 1"): (44, 61.4), ("RM301", "Checkpoint quiz"): (33, 69.0),
        ("DB201", "Problem Set 1"): (30, 56.8), ("DB201", "Checkpoint quiz"): (20, 66.6),
    }


def test_volumes(con):
    assert con.execute("SELECT count(*) FROM base.completion WHERE completed").fetchone()[0] == 2172
    assert con.execute("SELECT count(*) FROM base.course_completion WHERE completed").fetchone()[0] == 165
    assert con.execute("SELECT count(*) FROM base.activity").fetchone()[0] == 5 * 73


def test_schema_is_documented_and_free_of_personal_data(con, exports):
    schema = describe_schema(con)
    assert [t["name"] for t in schema] == [*TABLES, "export_meta"]
    for table in schema:
        assert table["comment"].strip(), table["name"]
        for column in table["columns"]:
            assert column["comment"].strip(), f"{table['name']}.{column['name']}"
            assert column["name"] not in PII_COLUMNS
    settings, _ = exports["duckdb"]
    assert settings.salt.encode() not in settings.db_path.read_bytes()


def test_parquet_mode_matches_duckdb_mode(con, exports):
    duck_settings, duck_result = exports["duckdb"]
    pq_settings, pq_result = exports["parquet"]
    assert pq_result.source == "parquet" and duck_result.source == "mysql"
    assert pq_result.row_counts == duck_result.row_counts
    other = duckdb.connect(str(pq_settings.db_path), read_only=True)
    try:
        shape = lambda c: [(t["name"], [(x["name"], x["type"]) for x in t["columns"]]) for t in describe_schema(c)]  # noqa: E731
        assert shape(other) == shape(con)
    finally:
        other.close()
    files = sorted(p.name for p in (pq_settings.data_dir / "parquet").iterdir())
    assert files == sorted(f"{t}.parquet" for t in (*TABLES, "export_meta"))
    assert not list(pq_settings.data_dir.glob(".staging-*"))
