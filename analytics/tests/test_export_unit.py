import time
from pathlib import Path

import duckdb
import pytest

from app.config import Settings
from app.db import READER_CONFIG
import app.export as export_mod
from app.export import SOURCE_COLUMNS, ExportBusy, ExportError, export, export_lock, publish, render_views_sql, sql_literal, user_ref

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


GRANTS_FILE = Path(__file__).resolve().parents[2] / "docker" / "db" / "analytics-tables.txt"


@pytest.mark.skipif(not GRANTS_FILE.exists(), reason="repository checkout only (not copied into the image)")
def test_grant_list_matches_source_columns():
    lines = [line.split() for line in GRANTS_FILE.read_text().splitlines() if line.strip() and not line.startswith("#")]
    assert {table: tuple(columns.split(",")) for table, columns in lines} == SOURCE_COLUMNS
    assert [table for table, _ in lines] == list(SOURCE_COLUMNS)


def _export_settings(tmp_path, **extra):
    return Settings.from_env({**ENV, "DATA_DIR": str(tmp_path), **extra})


def _fake_mysql(con, settings):
    from tests.fake_moodle import attach_fake_moodle

    attach_fake_moodle(con)


def test_settings_export_timeout(tmp_path):
    assert _export_settings(tmp_path).export_timeout_s == 600
    assert _export_settings(tmp_path, EXPORT_TIMEOUT_S="30").export_timeout_s == 30


def test_export_sweeps_leftovers_of_a_crashed_run(tmp_path, monkeypatch):
    monkeypatch.setattr(export_mod, "attach_mysql", _fake_mysql)
    for leftover in (".staging-abc123", "parquet.tmp", "parquet.old"):
        (tmp_path / leftover).mkdir()
        (tmp_path / leftover / "x.parquet").write_bytes(b"raw ids")
    (tmp_path / "moodle.duckdb.tmp").write_bytes(b"half written")
    result = export(_export_settings(tmp_path), now_epoch=1_790_000_000)
    assert result.row_counts["course"] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [".export.lock", "moodle.duckdb"]


def test_watchdog_cancels_a_stuck_export(tmp_path, monkeypatch):
    def stuck(con, settings):
        con.execute("SELECT count(*) FROM range(100000000000) a, range(1000) b").fetchall()

    monkeypatch.setattr(export_mod, "attach_mysql", stuck)
    start = time.monotonic()
    with pytest.raises(ExportError, match="EXPORT_TIMEOUT_S"):
        export(_export_settings(tmp_path, EXPORT_TIMEOUT_S="1"))
    assert time.monotonic() - start < 10
    assert not (tmp_path / "moodle.duckdb").exists()
    assert not (tmp_path / "moodle.duckdb.tmp").exists()


def test_parquet_export_publishes_duckdb_first(tmp_path, monkeypatch):
    from tests.fake_moodle import attach_fake_moodle

    def fake_stage(settings, staging_dir, watchdog=None):
        src = duckdb.connect()
        attach_fake_moodle(src)
        for table, columns in SOURCE_COLUMNS.items():
            cols = ", ".join(f'"{c}"' for c in columns)
            src.execute(f"COPY (SELECT {cols} FROM m.{table}) TO '{staging_dir / (table + '.parquet')}' (FORMAT parquet)")
        src.close()

    order = []
    real_publish, real_write = export_mod.publish, export_mod.write_parquet_outputs

    def spy_publish(tmp, final):
        order.append("publish")
        real_publish(tmp, final)

    def spy_write(db_file, out_dir):
        order.append("parquet")
        assert db_file == tmp_path / "moodle.duckdb" and db_file.exists()
        real_write(db_file, out_dir)

    monkeypatch.setattr(export_mod, "stage_parquet", fake_stage)
    monkeypatch.setattr(export_mod, "publish", spy_publish)
    monkeypatch.setattr(export_mod, "write_parquet_outputs", spy_write)
    result = export(_export_settings(tmp_path, EXPORT_FORMAT="parquet"), now_epoch=1_790_000_000)
    assert order == ["publish", "parquet"]
    assert result.source == "parquet"
    assert (tmp_path / "parquet" / "course.parquet").exists()
    assert not list(tmp_path.glob(".staging-*"))


def test_parquet_outputs_work_while_a_locked_reader_is_open(tmp_path):
    from tests.fake_moodle import NOW, attach_fake_moodle

    db = tmp_path / "moodle.duckdb"
    export_mod.build_database(db, attach_fake_moodle, "salt", NOW, "mysql")
    reader = duckdb.connect(str(db), read_only=True, config=READER_CONFIG)
    try:
        export_mod.write_parquet_outputs(db, tmp_path / "parquet")
    finally:
        reader.close()
    assert (tmp_path / "parquet" / "participant.parquet").exists()


def test_mysql_preflight_fails_fast_on_unreachable_host(tmp_path, monkeypatch):
    monkeypatch.setattr(export_mod, "MYSQL_CONNECT_TIMEOUT_S", 0.5)
    settings = _export_settings(tmp_path, ANALYTICS_DB_HOST="127.0.0.1", ANALYTICS_DB_PORT="9")
    con = duckdb.connect()
    start = time.monotonic()
    with pytest.raises(ExportError, match="cannot reach MySQL at 127.0.0.1:9"):
        export_mod.attach_mysql(con, settings)
    assert time.monotonic() - start < 5
    assert "pw-secret" not in str(ExportError)
