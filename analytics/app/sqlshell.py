"""Run one read-only query against the export and print a table: ``python -m app.sqlshell "SELECT ..."``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb

from app.config import DB_FILENAME
from app.db import READER_CONFIG


def main(argv: list[str]) -> int:
    query = " ".join(argv).strip()
    if not query:
        print('usage: python -m app.sqlshell "SELECT ..."', file=sys.stderr)
        return 2
    path = Path(os.environ.get("DATA_DIR", "/data")) / DB_FILENAME
    con = duckdb.connect(str(path), read_only=True, config=dict(READER_CONFIG))
    try:
        con.sql(query).show(max_width=200, max_rows=200)
    except duckdb.Error as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
