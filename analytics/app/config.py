"""Service settings read from the environment."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

EXPORT_FORMATS = ("duckdb", "parquet")
DB_FILENAME = "moodle.duckdb"

# The MySQL ATTACH string is space-separated key=value pairs, so values must not contain whitespace or quotes.
_DSN_VALUE_RE = re.compile(r"^[^\s'\"]+$")


def _int(env: Mapping[str, str], key: str, default: int, minimum: int) -> int:
    raw = env.get(key, "") or str(default)
    try:
        value = int(raw)
    except ValueError as err:
        raise ValueError(f"{key} must be an integer") from err
    if value < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    return value


@dataclass(frozen=True)
class Settings:
    db_user: str
    db_password: str = field(repr=False)
    salt: str = field(repr=False)
    db_host: str = "db"
    db_port: int = 3306
    db_name: str = "moodle"
    data_dir: Path = Path("/data")
    export_format: str = "duckdb"
    refresh_minutes: int = 15
    max_rows: int = 200

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        salt = env.get("ANALYTICS_SALT", "")
        if not salt:
            raise ValueError("ANALYTICS_SALT is required")
        export_format = env.get("EXPORT_FORMAT", "") or "duckdb"
        if export_format not in EXPORT_FORMATS:
            raise ValueError(f"EXPORT_FORMAT must be one of {', '.join(EXPORT_FORMATS)}")
        values = {
            "db_host": env.get("ANALYTICS_DB_HOST", "") or "db",
            "db_name": env.get("ANALYTICS_DB_NAME", "") or "moodle",
            "db_user": env.get("ANALYTICS_DB_USER", ""),
            "db_password": env.get("ANALYTICS_DB_PASSWORD", ""),
        }
        for key, value in values.items():
            if not _DSN_VALUE_RE.match(value):
                raise ValueError(f"{key} is empty or contains whitespace or quotes")
        return cls(
            salt=salt,
            db_port=_int(env, "ANALYTICS_DB_PORT", 3306, 1),
            data_dir=Path(env.get("DATA_DIR", "") or "/data"),
            export_format=export_format,
            refresh_minutes=_int(env, "REFRESH_MINUTES", 15, 0),
            max_rows=_int(env, "MAX_ROWS", 200, 1),
            **values,
        )
