"""HTTP API of the analytics service. Run with ``uvicorn --factory app.main:create_app``."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import duckdb
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.config import Settings
from app.db import READER_CONFIG
from app.export import ExportBusy, ExportError, ExportResult, export
from app.schema import describe_schema, schema_as_prompt_text

log = logging.getLogger("analytics.api")

ExportFn = Callable[[Settings], ExportResult]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    course_ids: list[int] = Field(min_length=1)
    user_ref: str = Field(min_length=1, max_length=128)


class AskResponse(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    elapsed_ms: float


class ExportRunner:
    """Runs one export at a time; a second caller gets ``ExportBusy``."""

    def __init__(self, settings: Settings, export_fn: ExportFn):
        self._settings = settings
        self._export_fn = export_fn
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def run(self) -> ExportResult:
        if not self._lock.acquire(blocking=False):
            raise ExportBusy("an export is already running")
        self._idle.clear()
        try:
            return self._export_fn(self._settings)
        finally:
            self._lock.release()
            self._idle.set()

    def run_logged(self) -> None:
        try:
            self.run()
        except ExportBusy:
            log.info("scheduled export skipped: another export is running")
        except ExportError as err:
            log.error("export failed: %s", err)
        except Exception as err:  # noqa: BLE001
            log.error("export failed: %s", type(err).__name__)

    def start_background(self) -> None:
        threading.Thread(target=self.run_logged, name="initial-export", daemon=True).start()

    def wait_idle(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)


async def _periodic(runner: ExportRunner, minutes: int) -> None:
    while True:
        await asyncio.sleep(minutes * 60)
        await asyncio.to_thread(runner.run_logged)


def create_app(
    settings: Settings | None = None,
    export_fn: ExportFn | None = None,
    refresh_on_startup: bool = True,
) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s %(message)s")
    settings = settings or Settings.from_env()
    runner = ExportRunner(settings, export_fn or export)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        if refresh_on_startup and not settings.db_path.exists():
            runner.start_background()
        task = asyncio.create_task(_periodic(runner, settings.refresh_minutes)) if settings.refresh_minutes > 0 else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="Moodle analytics", lifespan=lifespan)
    app.state.settings = settings
    app.state.runner = runner

    def reader() -> duckdb.DuckDBPyConnection:
        # One connection per request: see the publishing notes in app/export.py.
        return duckdb.connect(str(settings.db_path), read_only=True, config=dict(READER_CONFIG))

    def no_export() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"status": "starting", "db_file": False, "refreshing": runner.busy},
        )

    @app.get("/health")
    def health():
        if not settings.db_path.exists():
            return no_export()
        try:
            con = reader()
            try:
                exported_at, source, row_counts = con.execute(
                    "SELECT exported_at, source, row_counts FROM base.export_meta"
                ).fetchone()
            finally:
                con.close()
        except Exception as err:  # noqa: BLE001
            log.error("health check failed: %s", err)
            return JSONResponse(status_code=503, content={"status": "error", "db_file": True})
        return {
            "status": "ok",
            "db_file": True,
            "last_export": exported_at.isoformat(),
            "source": source,
            "row_counts": json.loads(row_counts),
            "refreshing": runner.busy,
        }

    @app.get("/schema")
    def schema(format: str = Query("json", pattern="^(json|text)$")):
        if not settings.db_path.exists():
            return no_export()
        con = reader()
        try:
            tables = describe_schema(con)
        finally:
            con.close()
        prompt = schema_as_prompt_text(tables)
        if format == "text":
            return PlainTextResponse(prompt)
        return {"tables": tables, "prompt": prompt}

    @app.post("/refresh")
    def refresh():
        try:
            result = runner.run()
        except ExportBusy as err:
            return JSONResponse(status_code=409, content={"detail": str(err)})
        except ExportError as err:
            log.error("export failed: %s", err)
            return JSONResponse(status_code=500, content={"detail": "export failed; see the analytics service logs"})
        except Exception as err:  # noqa: BLE001
            log.error("export failed: %s", type(err).__name__)
            return JSONResponse(status_code=500, content={"detail": "export failed; see the analytics service logs"})
        return result.to_dict()

    @app.post("/ask", response_model=AskResponse)
    def ask(request: AskRequest):
        # Phase d: generate SQL with the local model, then run it through
        # app.db.open_query_connection + run_guarded and return AskResponse.
        return JSONResponse(status_code=501, content={"detail": "/ask is not implemented yet"})

    return app
