"""Natural-language questions to guarded SQL with a local Ollama model.

Flow of one request: verify the HMAC signature over the raw body, build the
prompt (stable system rules and schema first, then the few-shot examples closest
to the question), ask Ollama for one SQL statement, run it through the guard on a
connection whose views only contain the signed ``course_ids``, and retry once with
the error message when the guard or DuckDB rejects it.
"""

from __future__ import annotations

import datetime as dt
import decimal
import hashlib
import hmac
import json
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import duckdb
import yaml

from app.db import QUERY_SCHEMA, QueryTimeout, open_query_connection, run_guarded
from app.guard import GuardError, extract_sql_from_model_output
from app.schema import QUERY_TABLES, describe_schema, schema_as_prompt_text

EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "examples.yaml"

TIMESTAMP_HEADER = "X-Askdata-Timestamp"
SIGNATURE_HEADER = "X-Askdata-Signature"

SYSTEM_RULES = """\
You write one DuckDB SQL query that answers a teacher's question about their Moodle courses.

Rules:
1. Reply with a single SELECT statement inside a ```sql code block and nothing else.
2. Use only the tables listed below. They already contain only the teacher's courses, so never filter by teacher.
3. user_ref is a pseudonymous id. Names and emails do not exist; never ask for them.
4. Students are participant rows with role = 'student'.
5. "Logged in" means the whole site: use days_since_last_login. "Accessed the course" means days_since_last_access. NULL means never.
6. Today is current_date. "Due this week" means due_at >= current_date AND due_at < current_date + INTERVAL 7 DAY.
7. Use readable column aliases. Include course.shortname whenever you group or list by course.
8. When you list individual students, end with LIMIT 200.
"""

RETRY_TEMPLATE = """\
This SQL failed:
```sql
{sql}
```
Fix the SQL. Error: {error}
Reply with the corrected query in a single ```sql code block."""

# ASCII only: str.isdigit() accepts "²" and int() then fails; hmac.compare_digest rejects non-ASCII str.
_TIMESTAMP_RE = re.compile(r"[0-9]{1,12}")
_SIGNATURE_RE = re.compile(r"[0-9a-f]{64}")

# Longest guard or DuckDB error fed back to the model and returned to the caller.
MAX_ERROR_CHARS = 300

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by did do does each for from has have how i in is it its me my "
    "of on or per show the their them this to was were what when which who with".split()
)


class ChatClient(Protocol):
    model: str

    def chat(self, messages: list[dict[str, str]], timeout_s: float | None = None) -> ChatResult: ...


@dataclass(frozen=True)
class ChatResult:
    content: str
    model_ms: float
    prompt_eval_tokens: int | None = None
    prompt_eval_ms: float | None = None
    eval_tokens: int | None = None
    eval_ms: float | None = None


@dataclass(frozen=True)
class Example:
    id: str
    question: str
    sql: str
    tags: tuple[str, ...] = ()


class AskError(Exception):
    """Request failure mapped to an HTTP status and a stable ``reason``."""

    def __init__(self, status: int, reason: str, message: str, sql: str | None = None, attempts: int = 0):
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.message = message
        self.sql = sql
        self.attempts = attempts

    def detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"reason": self.reason, "message": self.message}
        if self.sql is not None:
            detail["sql"] = self.sql
        return detail


# --- authentication -------------------------------------------------------------------


def sign(secret: str, method: str, path: str, timestamp: str | int, body: bytes) -> str:
    """Hex HMAC-SHA256 of ``METHOD\\nPATH\\nTIMESTAMP\\n`` followed by the raw body bytes."""
    message = f"{method.upper()}\n{path}\n{timestamp}\n".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_request(
    secret: str,
    method: str,
    path: str,
    timestamp: str | None,
    signature: str | None,
    body: bytes,
    window_s: int,
    now: float | None = None,
) -> None:
    if not secret:
        raise AskError(503, "not_configured", "ASKDATA_SHARED_SECRET is not set; /ask is disabled")
    if not timestamp or not signature:
        raise AskError(401, "missing_auth", f"send {TIMESTAMP_HEADER} and {SIGNATURE_HEADER} headers")
    if not _TIMESTAMP_RE.fullmatch(timestamp):
        raise AskError(401, "bad_signature", f"{TIMESTAMP_HEADER} must be unix seconds")
    signature = signature.strip().lower()
    if not _SIGNATURE_RE.fullmatch(signature):
        raise AskError(401, "bad_signature", f"{SIGNATURE_HEADER} must be 64 hex characters")
    now = time.time() if now is None else now
    if abs(now - int(timestamp)) > window_s:
        raise AskError(401, "expired", f"timestamp is outside the {window_s}s window; check the clocks")
    expected = sign(secret, method, path, timestamp, body)
    if not hmac.compare_digest(expected, signature):
        raise AskError(401, "bad_signature", "signature does not match the request")


# --- few-shot examples ----------------------------------------------------------------


def load_examples(path: Path = EXAMPLES_PATH) -> list[Example]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [
        Example(id=e["id"], question=e["question"], sql=e["sql"].strip(), tags=tuple(e.get("tags") or ()))
        for e in raw
    ]


def _words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


def select_examples(question: str, examples: Sequence[Example], k: int) -> list[Example]:
    """Top ``k`` examples by Jaccard similarity of word sets (question plus tags)."""
    if k <= 0:
        return []
    q = _words(question)

    def score(example: Example) -> float:
        words = _words(example.question + " " + " ".join(example.tags))
        union = q | words
        return len(q & words) / len(union) if union else 0.0

    ranked = sorted(enumerate(examples), key=lambda item: (-score(item[1]), item[0]))
    return [example for _, example in ranked[:k]]


def build_messages(schema_text: str, examples: Sequence[Example], question: str) -> list[dict[str, str]]:
    """System prompt first and identical across requests, so Ollama can reuse its KV cache."""
    messages = [{"role": "system", "content": f"{SYSTEM_RULES}\nTables:\n\n{schema_text}"}]
    # Least similar first: the closest example sits right before the question.
    for example in reversed(examples):
        messages.append({"role": "user", "content": example.question})
        messages.append({"role": "assistant", "content": f"```sql\n{example.sql}\n```"})
    messages.append({"role": "user", "content": question})
    return messages


# --- Ollama ---------------------------------------------------------------------------


class OllamaClient:
    def __init__(self, base_url: str, model: str, num_ctx: int, keep_alive: str, timeout_s: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.timeout_s = timeout_s

    def chat(self, messages: list[dict[str, str]], timeout_s: float | None = None) -> ChatResult:
        timeout_s = self.timeout_s if timeout_s is None else timeout_s
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                body = json.load(response)
        except urllib.error.HTTPError as err:
            raise AskError(502, "model_unavailable", self._http_error(err)) from None
        except (TimeoutError, socket.timeout):
            raise AskError(504, "timeout", f"the model did not answer within {timeout_s:g}s") from None
        except urllib.error.URLError as err:
            if isinstance(err.reason, (TimeoutError, socket.timeout)):
                raise AskError(504, "timeout", f"the model did not answer within {timeout_s:g}s") from None
            raise AskError(502, "model_unavailable", f"Ollama is not reachable at {self.base_url}") from None
        except (OSError, ValueError):
            raise AskError(502, "model_unavailable", f"Ollama at {self.base_url} returned an unreadable answer") from None
        elapsed = (time.perf_counter() - start) * 1000.0
        content = (body.get("message") or {}).get("content") or ""
        ns = lambda key: round(body[key] / 1e6, 1) if isinstance(body.get(key), (int, float)) else None  # noqa: E731
        return ChatResult(
            content=content,
            model_ms=elapsed,
            prompt_eval_tokens=body.get("prompt_eval_count"),
            prompt_eval_ms=ns("prompt_eval_duration"),
            eval_tokens=body.get("eval_count"),
            eval_ms=ns("eval_duration"),
        )

    def _http_error(self, err: urllib.error.HTTPError) -> str:
        try:
            detail = json.loads(err.read() or b"{}").get("error", "")
        except ValueError:
            detail = ""
        if err.code == 404:
            return f"model '{self.model}' is not available in Ollama; run `make init-model`"
        return f"Ollama returned HTTP {err.code}" + (f": {detail}" if detail else "")


# --- answering ------------------------------------------------------------------------


@dataclass
class AskResult:
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    elapsed_ms: float
    attempts: int
    truncated: bool
    model: str
    timings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sql": self.sql,
            "columns": self.columns,
            "rows": self.rows,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "attempts": self.attempts,
            "truncated": self.truncated,
            "model": self.model,
            "timings": self.timings,
        }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _clip(text: str, limit: int = MAX_ERROR_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _duckdb_message(err: duckdb.Error) -> str:
    # Drop the "LINE n:" excerpt: it shows the guard's wrapper query, not the model's SQL.
    text = str(err).split("\n\nLINE ", 1)[0].split("\nLINE ", 1)[0]
    return " ".join(text.split())


def answer(
    question: str,
    course_ids: Iterable[int],
    max_rows: int,
    db_path: str,
    client: ChatClient,
    examples: Sequence[Example],
    top_k: int,
    query_timeout_s: float,
    tables: dict[str, str | None] | None = None,
    clock: Callable[[], float] = time.perf_counter,
    model_budget_s: float | None = None,
) -> AskResult:
    """Generate, guard and run SQL for ``question``; one retry with the error message.

    ``model_budget_s`` bounds the time from the start of the request to the end of the last
    model call, so the retry only gets what the first attempt left.
    """
    tables = dict(QUERY_TABLES if tables is None else tables)
    allowed = set(tables)
    start = clock()
    con = open_query_connection(db_path, course_ids, tables)
    try:
        schema = [t for t in describe_schema(con, QUERY_SCHEMA) if t["name"] in allowed]
        messages = build_messages(schema_as_prompt_text(schema), select_examples(question, examples, top_k), question)
        model_ms = sql_ms = 0.0
        calls: list[dict[str, Any]] = []
        sql = ""
        reason, message = "sql_rejected", ""
        for attempt in (1, 2):
            timeout_s = None
            if model_budget_s is not None:
                timeout_s = model_budget_s - (clock() - start)
                if timeout_s < 1:
                    message = f"the model did not answer within {model_budget_s:g}s"
                    raise AskError(504, "timeout", message, sql=sql or None, attempts=attempt - 1)
            reply = client.chat(messages, timeout_s=timeout_s)
            model_ms += reply.model_ms
            calls.append(
                {
                    "model_ms": round(reply.model_ms, 1),
                    "prompt_tokens": reply.prompt_eval_tokens,
                    "prompt_ms": reply.prompt_eval_ms,
                    "output_tokens": reply.eval_tokens,
                    "output_ms": reply.eval_ms,
                }
            )
            sql = extract_sql_from_model_output(reply.content)
            sql_start = clock()
            try:
                columns, rows, _ = run_guarded(con, sql, allowed, max_rows + 1, query_timeout_s)
            except GuardError as err:
                reason, message = "sql_rejected", _clip(err.message)
            except QueryTimeout as err:
                raise AskError(504, "timeout", str(err), sql=sql, attempts=attempt) from None
            except duckdb.Error as err:
                reason, message = "sql_error", _clip(_duckdb_message(err))
            else:
                sql_ms += (clock() - sql_start) * 1000.0
                truncated = len(rows) > max_rows
                return AskResult(
                    sql=sql,
                    columns=columns,
                    rows=[[_jsonable(v) for v in row] for row in rows[:max_rows]],
                    elapsed_ms=(clock() - start) * 1000.0,
                    attempts=attempt,
                    truncated=truncated,
                    model=client.model,
                    timings={
                        "model_ms": round(model_ms, 1),
                        "sql_ms": round(sql_ms, 1),
                        "calls": calls,
                    },
                )
            sql_ms += (clock() - sql_start) * 1000.0
            messages = [
                *messages,
                {"role": "assistant", "content": reply.content},
                {"role": "user", "content": RETRY_TEMPLATE.format(sql=sql, error=message)},
            ]
        raise AskError(422, reason, f"the model could not write a valid query after 2 attempts: {message}", sql=sql, attempts=2)
    finally:
        con.close()
