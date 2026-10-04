"""views.sql against a tiny fake Moodle catalog, both through a direct catalog and Parquet staging."""

import datetime as dt
import json

import duckdb
import pytest

from app.export import (
    SOURCE_COLUMNS,
    TABLES,
    attach_parquet_staging,
    build_database,
    user_ref,
)
from app.schema import describe_schema
from tests.fake_moodle import DAY, NOW, attach_fake_moodle

SALT = "unit-test-salt-6f1e"
PII_COLUMNS = {"firstname", "lastname", "email", "username", "ip", "lastip", "password", "phone1", "phone2", "address"}


@pytest.fixture
def built(tmp_path):
    path = tmp_path / "moodle.duckdb"
    counts = build_database(path, attach_fake_moodle, SALT, NOW, "mysql")
    con = duckdb.connect(str(path), read_only=True)
    yield con, counts, path
    con.close()


def rows(con, sql):
    return con.execute(sql).fetchall()


def ts(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).replace(tzinfo=None)


def test_user_ref_matches_duckdb_sha256():
    expected = duckdb.sql(f"SELECT sha256('10' || '{SALT}')").fetchone()[0]
    assert user_ref(10, SALT) == expected
    assert len(expected) == 64


def test_row_counts_are_returned_for_every_table(built):
    con, counts, _ = built
    assert set(counts) == set(TABLES)
    assert counts == {
        "course": 2,
        "participant": 7,
        "daily_activity": 2,
        "activity": 4,
        "completion": 3,
        "course_completion": 2,
        "grade_item": 3,
        "grade": 2,
        "assignment_submission": 2,
    }
    for table, n in counts.items():
        assert rows(con, f"SELECT count(*) FROM base.{table}")[0][0] == n


def test_course_excludes_site_and_converts_dates(built):
    con, _, _ = built
    assert rows(con, "SELECT course_id, shortname, start_date, visible, completion_enabled FROM base.course ORDER BY 1") == [
        (2, "C1", ts(NOW - 60 * DAY).date(), True, True),
        (3, "C2", None, False, False),
    ]


def test_participant_roles_access_and_pseudonyms(built):
    con, _, _ = built
    got = rows(
        con,
        "SELECT course_id, user_ref, role, enrolled_at, last_access_at, days_since_last_access, "
        "days_since_last_login, suspended "
        "FROM base.participant ORDER BY course_id, role, days_since_last_access NULLS LAST, enrolled_at",
    )
    assert got == [
        (2, user_ref(12, SALT), "editingteacher", ts(NOW - 40 * DAY).date(), ts(NOW - 2 * DAY), 2, 2, False),
        (2, user_ref(14, SALT), "student", ts(NOW - 50 * DAY).date(), ts(NOW - 3 * DAY), 3, 3, True),
        (2, user_ref(10, SALT), "student", ts(NOW - 30 * DAY).date(), ts(NOW - 20 * DAY - 3600), 20, 1, False),
        (2, user_ref(11, SALT), "student", ts(NOW - 29 * DAY).date(), None, None, None, False),
        (2, user_ref(15, SALT), "student", ts(NOW + 5 * DAY).date(), None, None, None, True),
        (2, user_ref(12, SALT), "teacher", ts(NOW - 40 * DAY).date(), ts(NOW - 2 * DAY), 2, 2, False),
        (3, user_ref(10, SALT), "student", ts(NOW - 10 * DAY).date(), ts(NOW - DAY), 1, 1, True),
    ]


def test_participant_has_one_row_per_role_and_no_deleted_users(built):
    con, _, _ = built
    roles = rows(con, f"SELECT role FROM base.participant WHERE course_id = 2 AND user_ref = '{user_ref(12, SALT)}' ORDER BY role")
    assert roles == [("editingteacher",), ("teacher",)]
    assert rows(con, "SELECT count(DISTINCT user_ref) FROM base.participant WHERE course_id = 2")[0][0] == 5


@pytest.mark.parametrize(
    "table", ["participant", "daily_activity", "completion", "course_completion", "grade", "assignment_submission"]
)
def test_deleted_users_appear_nowhere(built, table):
    con, _, _ = built
    assert rows(con, f"SELECT count(*) FROM base.{table} WHERE user_ref = '{user_ref(13, SALT)}'") == [(0,)]


@pytest.mark.parametrize("table", ["activity", "completion", "grade_item", "assignment_submission"])
def test_modules_being_deleted_appear_nowhere(built, table):
    con, _, _ = built
    assert rows(con, f"SELECT count(*) FROM base.{table} WHERE cm_id IN (1004, 1005)") == [(0,)]
    assert rows(con, "SELECT count(*) FROM base.grade WHERE grade_item_id = 54") == [(0,)]


def test_daily_activity_counts_web_events_in_real_courses(built):
    con, _, _ = built
    assert rows(con, "SELECT course_id, user_ref, day, events, views, distinct_activities FROM base.daily_activity ORDER BY events DESC") == [
        (2, user_ref(10, SALT), ts(NOW - 20 * DAY).date(), 3, 2, 2),
        (2, user_ref(12, SALT), ts(NOW - 2 * DAY).date(), 1, 0, 1),
    ]


def test_activity_names_sections_and_due_dates(built):
    con, _, _ = built
    assert rows(con, "SELECT cm_id, module, name, section, visible, completion_tracked, due_at FROM base.activity ORDER BY cm_id") == [
        (1000, "page", "Welcome", 1, True, True, None),
        (1001, "assign", "Final Project", 2, True, True, ts(NOW + 3 * DAY)),
        (1002, "quiz", "Checkpoint quiz", 2, False, False, None),
        (1003, "lti", None, 0, True, False, None),
    ]


def test_completion_states(built):
    con, _, _ = built
    assert rows(con, "SELECT cm_id, user_ref, state, completed, completed_at FROM base.completion ORDER BY cm_id, state DESC") == [
        (1000, user_ref(10, SALT), 1, True, ts(NOW - 20 * DAY)),
        (1000, user_ref(11, SALT), 0, False, None),
        (1001, user_ref(10, SALT), 2, True, ts(NOW - 19 * DAY)),
    ]
    assert rows(con, "SELECT user_ref, completed, completed_at FROM base.course_completion ORDER BY completed DESC") == [
        (user_ref(10, SALT), True, ts(NOW - 18 * DAY)),
        (user_ref(11, SALT), False, None),
    ]


def test_grade_items_and_grades(built):
    con, _, _ = built
    assert rows(con, "SELECT grade_item_id, cm_id, item_name, item_type, item_module, grade_max FROM base.grade_item ORDER BY 1") == [
        (50, None, "Course total", "course", None, 100.0),
        (51, 1001, "Final Project", "mod", "assign", 100.0),
        (52, 1002, "Checkpoint quiz", "mod", "quiz", 10.0),
    ]
    assert rows(con, "SELECT grade_item_id, user_ref, final_grade, raw_grade FROM base.grade ORDER BY 1") == [
        (51, user_ref(10, SALT), 72.5, 70.0),
        (52, user_ref(10, SALT), 8.0, 8.0),
    ]


def test_assignment_submissions(built):
    con, _, _ = built
    assert rows(con, "SELECT cm_id, assignment_id, user_ref, status, submitted_at, latest FROM base.assignment_submission ORDER BY status DESC") == [
        (1001, 1, user_ref(10, SALT), "submitted", ts(NOW - 19 * DAY), True),
        (1001, 1, user_ref(11, SALT), "new", None, True),
    ]


def test_export_meta_records_time_source_and_counts(built):
    con, counts, _ = built
    exported_at, source, row_counts = rows(con, "SELECT * FROM base.export_meta")[0]
    assert exported_at == ts(NOW)
    assert source == "mysql"
    assert json.loads(row_counts) == counts


def test_every_table_and_column_is_commented(built):
    con, _, _ = built
    schema = describe_schema(con)
    assert [t["name"] for t in schema] == [*TABLES, "export_meta"]
    for table in schema:
        assert table["comment"], table["name"]
        for column in table["columns"]:
            assert column["comment"], f"{table['name']}.{column['name']}"


def test_no_personal_columns_and_no_salt_in_file(built):
    con, _, path = built
    names = {c["name"] for t in describe_schema(con) for c in t["columns"]}
    assert not names & PII_COLUMNS
    con.close()
    data = path.read_bytes()
    assert SALT.encode() not in data
    for leaked in (b"alice@example.com", b"Alice", b"10.0.0.1", b"secret summary"):
        assert leaked not in data


def test_source_columns_whitelist_has_no_personal_data():
    for table, columns in SOURCE_COLUMNS.items():
        assert not set(columns) & PII_COLUMNS, table


def test_parquet_staging_of_whitelisted_columns_gives_same_result(tmp_path, built):
    con, counts, _ = built
    staging = tmp_path / "staging"
    staging.mkdir()
    src = duckdb.connect()
    attach_fake_moodle(src)
    for table, columns in SOURCE_COLUMNS.items():
        cols = ", ".join(f'"{c}"' for c in columns)
        src.execute(f"COPY (SELECT {cols} FROM m.{table}) TO '{staging / (table + '.parquet')}' (FORMAT parquet)")
    src.close()

    path = tmp_path / "from_parquet.duckdb"
    parquet_counts = build_database(path, lambda c: attach_parquet_staging(c, staging), SALT, NOW, "parquet")
    assert parquet_counts == counts
    other = duckdb.connect(str(path), read_only=True)
    try:
        assert [(t["name"], [(c["name"], c["type"]) for c in t["columns"]]) for t in describe_schema(other)] == [
            (t["name"], [(c["name"], c["type"]) for c in t["columns"]]) for t in describe_schema(con)
        ]
        for table in TABLES:
            q = f"SELECT * FROM base.{table} ORDER BY ALL"
            assert other.execute(q).fetchall() == con.execute(q).fetchall(), table
    finally:
        other.close()
