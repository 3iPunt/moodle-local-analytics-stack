import duckdb
import pytest

from app.config import Settings
from app.db import READER_CONFIG
from app.export import ExportBusy, export_lock, publish, render_views_sql, sql_literal, user_ref

ENV = {
    "ANALYTICS_DB_USER": "ro",
    "ANALYTICS_DB_PASSWORD": "pw-secret",
    "ANALYTICS_SALT": "salt-secret",
}


def test_sql_literal_escapes_quotes():
    assert sql_literal("a'b") == "'a''b'"
    assert duckdb.sql(f"SELECT {sql_literal(chr(39) + 'x' + chr(39))}").fetchone()[0] == "'x'"


def test_render_substitutes_placeholders_as_literals():
    sql = render_views_sql("SELECT {salt}, {now_epoch}", "o'clock", 1234)
    assert sql == "SELECT 'o''clock', 1234"


def test_render_rejects_non_integer_epoch():
    with pytest.raises(ValueError):
        render_views_sql("SELECT {now_epoch}", "s", "1; DROP")


def test_user_ref_is_md5_of_id_and_salt():
    assert user_ref(103, "s") != user_ref(103, "t")
    assert user_ref(103, "s") == duckdb.sql("SELECT md5('103s')").fetchone()[0]


def test_settings_from_env_defaults_and_hidden_secrets(tmp_path):
    s = Settings.from_env({**ENV, "DATA_DIR": str(tmp_path)})
    assert s.db_host == "db" and s.db_port == 3306 and s.db_name == "moodle"
    assert s.export_format == "duckdb" and s.refresh_minutes == 15 and s.max_rows == 200
    assert s.db_path == tmp_path / "moodle.duckdb"
    assert "pw-secret" not in repr(s) and "salt-secret" not in repr(s)


@pytest.mark.parametrize(
    "override",
    [{"ANALYTICS_SALT": ""}, {"EXPORT_FORMAT": "csv"}, {"REFRESH_MINUTES": "-1"}, {"ANALYTICS_DB_PASSWORD": "a b"}],
)
def test_settings_reject_invalid_values(override):
    with pytest.raises(ValueError):
        Settings.from_env({**ENV, **override})


def _make_db(path, value):
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t AS SELECT ? AS v", [value])
    con.close()


def test_publish_swaps_atomically_and_keeps_open_readers_working(tmp_path):
    final = tmp_path / "moodle.duckdb"
    tmp = tmp_path / "moodle.duckdb.tmp"
    _make_db(final, 1)
    _make_db(tmp, 2)
    (tmp_path / "moodle.duckdb.wal").write_bytes(b"stale")

    reader = duckdb.connect(str(final), read_only=True, config=READER_CONFIG)
    publish(tmp, final)
    assert not tmp.exists()
    assert not (tmp_path / "moodle.duckdb.wal").exists()
    assert reader.execute("SELECT v FROM t").fetchone()[0] == 1
    reader.close()

    fresh = duckdb.connect(str(final), read_only=True, config=READER_CONFIG)
    assert fresh.execute("SELECT v FROM t").fetchone()[0] == 2
    fresh.close()


def test_export_lock_is_exclusive(tmp_path):
    with export_lock(tmp_path):
        with pytest.raises(ExportBusy):
            with export_lock(tmp_path):
                pass
    with export_lock(tmp_path):
        pass
