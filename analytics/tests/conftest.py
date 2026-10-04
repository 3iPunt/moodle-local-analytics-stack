import duckdb
import pytest

ALLOWED = {"course", "participant"}
TABLES = {"course": "course_id", "participant": "course_id"}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "moodle.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA base")
    con.execute("CREATE TABLE base.course (course_id INTEGER, shortname VARCHAR, fullname VARCHAR)")
    con.execute(
        "CREATE TABLE base.participant "
        "(course_id INTEGER, user_ref VARCHAR, role VARCHAR, last_access TIMESTAMP)"
    )
    con.execute("INSERT INTO base.course VALUES (1, 'c1', 'Course 1'), (2, 'c2', 'Course 2'), (3, 'c3', 'Course 3')")
    rows = [(cid, f"u{cid}_{i}", "student", "2026-01-01 10:00:00") for cid in (1, 2, 3) for i in range(5)]
    con.executemany("INSERT INTO base.participant VALUES (?, ?, ?, ?)", rows)
    con.close()
    return str(path)
