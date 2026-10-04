"""HTTP API of the analytics service. Run with ``uvicorn --factory app.main:create_app``."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import duckdb
from fastapi import FastAPI, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, StrictInt, ValidationError

from app.ask import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    AskError,
    ChatClient,
    OllamaClient,
    answer,
    load_examples,
    verify_request,
)
from app.config import Settings
from app.db import READER_CONFIG
from app.export import ExportBusy, ExportError, ExportResult, export
from app.schema import describe_schema, schema_as_prompt_text

log = logging.getLogger("analytics.api")
ask_log = logging.getLogger("analytics.ask")

ExportFn = Callable[[Settings], ExportResult]

STARTUP_RETRY_INITIAL_S = 5.0
STARTUP_RETRY_MAX_S = 60.0

# Largest request body accepted by /ask and /refresh. A valid /ask body is a few KiB.
MAX_BODY_BYTES = 64 * 1024
BUSY_RETRY_AFTER_S = 10


async def read_body(request: Request, limit: int = MAX_BODY_BYTES) -> bytes:
    """Read the raw body, refusing more than ``limit`` bytes before buffering them."""
    length = request.headers.get("content-length")
    if length is not None and length.isascii() and length.isdigit() and int(length) > limit:
        raise AskError(413, "too_large", f"the request body is larger than {limit} bytes")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise AskError(413, "too_large", f"the request body is larger than {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # Course scope of the request. It is covered by the signature and is the only
    # source of course filtering; user_ref is used for logging only.
    course_ids: list[StrictInt] = Field(min_length=1, max_length=200)
    user_ref: str = Field(pattern=r"^[0-9a-fA-F]{8,128}$")
    max_rows: StrictInt | None = Field(default=None, ge=1)


class AskResponse(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    elapsed_ms: float
    attempts: int
    truncated: bool
    model: str
    timings: dict[str, Any]


class ExportRunner:
    """Runs one export at a time; a second caller gets ``ExportBusy``."""

    def __init__(self, settings: Settings, export_fn: ExportFn):
        self._settings = settings
        self._export_fn = export_fn
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        # Set after the first successful export of this process.
        self.ready = threading.Event()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def run(self) -> ExportResult:
        if not self._lock.acquire(blocking=False):
            raise ExportBusy("an export is already running")
        self._idle.clear()
        try:
            result = self._export_fn(self._settings)
            self.ready.set()
            return result
        finally:
            self._lock.release()
            self._idle.set()

    def run_logged(self) -> bool:
        try:
            self.run()
            return True
        except ExportBusy:
            log.info("export skipped: another export is running")
        except ExportError as err:
            log.error("export failed: %s", err)
        except Exception as err:  # noqa: BLE001
            log.error("export failed: %s", type(err).__name__)
        return False

    def run_until_success(
        self,
        stop: threading.Event,
        initial_s: float = STARTUP_RETRY_INITIAL_S,
        maximum_s: float = STARTUP_RETRY_MAX_S,
        wait: Callable[[float], bool] | None = None,
    ) -> int:
        """Export until one run succeeds, backing off from ``initial_s`` to ``maximum_s``.

        ``wait`` returns True when ``stop`` was set while waiting. Returns the number of attempts.
        """
        wait = wait or stop.wait
        delay, attempts = initial_s, 0
        while not stop.is_set():
            attempts += 1
            if self.run_logged():
                return attempts
            log.info("startup export attempt %d failed, retrying in %gs", attempts, delay)
            if wait(delay):
                break
            delay = min(delay * 2, maximum_s)
        return attempts

    def start_background(self, stop: threading.Event) -> None:
        threading.Thread(target=self.run_until_success, args=(stop,), name="startup-export", daemon=True).start()

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
    chat_client: ChatClient | None = None,
) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s %(message)s")
    settings = settings or Settings.from_env()
    runner = ExportRunner(settings, export_fn or export)
    chat_client = chat_client or OllamaClient(
        settings.ollama_url,
        settings.ollama_model,
        settings.ollama_num_ctx,
        settings.ollama_keep_alive,
        settings.ollama_timeout_s,
    )
    examples = load_examples()
    # Bounds the concurrent /ask requests, and with it the DuckDB memory in use:
    # ASK_CONCURRENCY x DUCKDB_MEMORY_LIMIT.
    ask_slots = threading.BoundedSemaphore(settings.ask_concurrency)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        # Always export on startup: an existing file may be hours old. Moodle may still
        # be installing on a fresh stack, so retry until the first success.
        stop = threading.Event()
        if refresh_on_startup:
            runner.start_background(stop)
        task = asyncio.create_task(_periodic(runner, settings.refresh_minutes)) if settings.refresh_minutes > 0 else None
        yield
        stop.set()
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

    async def verify(request: Request, body: bytes | None = None) -> None:
        """Check the HMAC headers over ``body`` (read from the request when None)."""
        if body is None:
            body = await read_body(request)
        verify_request(
            settings.askdata_secret,
            request.headers.get(TIMESTAMP_HEADER),
            request.headers.get(SIGNATURE_HEADER),
            body,
            settings.replay_window_s,
        )

    def is_signed(request: Request) -> bool:
        return TIMESTAMP_HEADER in request.headers or SIGNATURE_HEADER in request.headers

    @app.get("/health")
    async def health(request: Request):
        # Unsigned: liveness only, for the container healthcheck. Signed: export details.
        if not is_signed(request):
            if not settings.db_path.exists():
                return JSONResponse(status_code=503, content={"status": "starting"})
            return {"status": "ok"}
        try:
            await verify(request)
        except AskError as err:
            log.info("health rejected outcome=%s", err.reason)
            return ask_error(err)
        return await run_in_threadpool(health_detail)

    def health_detail():
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
    async def schema(request: Request, format: str = Query("json", pattern="^(json|text)$")):
        try:
            await verify(request)
        except AskError as err:
            log.info("schema rejected outcome=%s", err.reason)
            return ask_error(err)
        return await run_in_threadpool(schema_body, format)

    def schema_body(format: str):
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
    async def refresh(request: Request):
        # Same signature scheme as /ask, over the raw body (usually empty).
        try:
            await verify(request)
        except AskError as err:
            log.info("refresh rejected outcome=%s", err.reason)
            return ask_error(err)
        try:
            result = await run_in_threadpool(runner.run)
        except ExportBusy as err:
            return JSONResponse(status_code=409, content={"detail": str(err)})
        except ExportError as err:
            log.error("export failed: %s", err)
            return JSONResponse(status_code=500, content={"detail": "export failed; see the analytics service logs"})
        except Exception as err:  # noqa: BLE001
            log.error("export failed: %s", type(err).__name__)
            return JSONResponse(status_code=500, content={"detail": "export failed; see the analytics service logs"})
        return result.to_dict()

    def ask_error(err: AskError) -> JSONResponse:
        return JSONResponse(status_code=err.status, content={"detail": err.detail()})

    @app.post("/ask", response_model=AskResponse)
    async def ask(request: Request):
        # The signature covers the exact bytes received, so read them before parsing.
        try:
            raw = await read_body(request)
            await verify(request, raw)
        except AskError as err:
            ask_log.info("ask rejected outcome=%s", err.reason)
            return ask_error(err)
        try:
            body = AskRequest.model_validate_json(raw)
        except ValidationError as err:
            errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in err.errors()]
            return JSONResponse(status_code=422, content={"detail": errors})
        if not settings.db_path.exists():
            return no_export()
        if not ask_slots.acquire(blocking=False):
            ask_log.info("ask rejected user_ref=%s outcome=busy", body.user_ref)
            return JSONResponse(
                status_code=503,
                content={
                    "detail": {"reason": "busy", "message": "the service is answering other questions; try again shortly"}
                },
                headers={"Retry-After": str(BUSY_RETRY_AFTER_S)},
            )

        max_rows = min(settings.max_rows, body.max_rows or settings.max_rows)
        ask_log.debug("ask user_ref=%s question=%r", body.user_ref, body.question)
        start = time.perf_counter()
        attempts, outcome = 0, "ok"
        try:
            result = await run_in_threadpool(
                answer,
                body.question,
                body.course_ids,
                max_rows,
                str(settings.db_path),
                chat_client,
                examples,
                settings.examples_top_k,
                settings.query_timeout_s,
                model_budget_s=settings.ollama_timeout_s,
            )
            attempts = result.attempts
            return result.to_dict()
        except AskError as err:
            attempts, outcome = err.attempts, err.reason
            return ask_error(err)
        except Exception as err:  # noqa: BLE001
            outcome = "internal_error"
            log.error("ask failed: %s", type(err).__name__)
            return JSONResponse(
                status_code=500,
                content={"detail": {"reason": "internal_error", "message": "see the analytics service logs"}},
            )
        finally:
            # run_in_threadpool waits for the worker thread even on cancellation, so the slot
            # is only released once the DuckDB connection is closed.
            ask_slots.release()
            ask_log.info(
                "ask user_ref=%s courses=%d attempts=%d elapsed_ms=%.0f outcome=%s",
                body.user_ref,
                len(body.course_ids),
                attempts,
                (time.perf_counter() - start) * 1000.0,
                outcome,
            )

    return app
