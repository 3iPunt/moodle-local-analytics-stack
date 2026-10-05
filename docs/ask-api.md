# /ask API

`POST http://analytics:8000/ask`, reachable only on the internal `backend` network. The Moodle plugin (`local_askdata`) and `make ask` use it.

## Authentication

Every request is signed with the shared secret `ASKDATA_SHARED_SECRET`.

| Header | Value |
|---|---|
| `X-Askdata-Timestamp` | Unix time in seconds, 1 to 12 ASCII digits |
| `X-Askdata-Signature` | Hex of `HMAC-SHA256(secret, METHOD + "\n" + PATH + "\n" + timestamp + "\n" + body)`, 64 characters (case is ignored) |

A header in any other format (a sign, a decimal point, a non-ASCII digit such as `²`, a non-hex character) gets 401 `bad_signature` before any comparison.

`METHOD` is the upper-case HTTP method and `PATH` is the request path without the query string (for example `POST` and `/ask`). The service uses the path it received, so a client behind a prefix signs the prefixed path. A signature is valid only for the endpoint it was made for: one captured from `GET /health` does not work on `POST /refresh`. A signature in the old `timestamp + "\n" + body` form gets 401 `bad_signature`.

`body` is the exact byte string sent as the request body. The service checks the signature over the raw bytes before it parses the JSON, so the client must sign the same bytes it sends. PHP:

```php
$body = json_encode($payload);
$ts = (string) time();
$sig = hash_hmac('sha256', "POST\n/ask\n" . $ts . "\n" . $body, $secret);
```

Requests older or newer than `ASKDATA_REPLAY_WINDOW_S` (default 300 s) are rejected. There is no nonce, so a captured request can be replayed on the same endpoint inside that window (replay on a different endpoint or method is rejected) (see [security.md](security.md#known-limits)). When `ASKDATA_SHARED_SECRET` is empty the endpoint answers 503 to everything.

Bodies larger than 64 KiB get 413 `too_large`. The service checks `Content-Length` before it reads anything, and stops reading a chunked body as soon as it passes the limit. A valid `/ask` body is a few KiB.

## Request

```json
{"question": "Which students have not logged in for 14 days?", "course_ids": [2, 3, 4], "user_ref": "9f2c41d0a7b3e815", "max_rows": 100}
```

| Field | Rule |
|---|---|
| `question` | 1 to 2000 characters |
| `course_ids` | 1 to 200 integers. The only course scope: every view the model sees is filtered to these ids. The plugin sends the courses the user teaches. |
| `user_ref` | Hex, 8 to 128 characters. Pseudonymous id, used for logging only. |
| `max_rows` | Optional, at least 1. The service uses `min(MAX_ROWS, max_rows)`. |

## Response

```json
{
  "sql": "SELECT ...",
  "columns": ["shortname", "user_ref"],
  "rows": [["DA101", "0d1f..."]],
  "elapsed_ms": 9024.3,
  "attempts": 1,
  "truncated": false,
  "model": "qwen2.5-coder:1.5b",
  "timings": {"model_ms": 8939.0, "sql_ms": 37.0, "calls": [{"model_ms": 8939.0, "prompt_tokens": 2839, "prompt_ms": 6898.0, "output_tokens": 61, "output_ms": 1992.0}]}
}
```

The first four fields are the stable contract. `truncated` is true when the query had more rows than the effective `max_rows`. The API returns data only; any explanation text is up to the caller.

## Errors

Errors use `{"detail": {"reason": "...", "message": "..."}}`. The message is meant for the user and never includes a stack trace.

| Status | Reason | When |
|---|---|---|
| 401 | `missing_auth` | A header is missing |
| 401 | `expired` | Timestamp outside the replay window |
| 401 | `bad_signature` | Signature does not match, or a header is malformed |
| 413 | `too_large` | Body over 64 KiB (checked before authentication) |
| 503 | `not_configured` | `ASKDATA_SHARED_SECRET` is empty |
| 503 | `busy` | `ASK_CONCURRENCY` questions are already running. Answered at once, with `Retry-After: 10`. |
| 422 | (validation list) | Body does not match the rules above |
| 422 | `sql_rejected` | The guard rejected the SQL twice. `detail.sql` has the last attempt. |
| 422 | `sql_error` | DuckDB rejected the SQL twice. `detail.sql` has the last attempt. |
| 502 | `model_unavailable` | Ollama is down, the model is not pulled, or the runner died (for example out of memory) |
| 504 | `timeout` | The model calls used up `OLLAMA_TIMEOUT_S`, or a query ran over 30 s |

## How a question is answered

1. The prompt starts with fixed rules and the schema, the same for every request, so Ollama reuses that part of its KV cache.
2. Then come the `EXAMPLES_TOP_K` examples from `analytics/examples.yaml` whose words overlap most with the question (Jaccard over word sets), closest one last.
3. Ollama answers with `temperature` 0 and `num_ctx` `OLLAMA_NUM_CTX`. The SQL goes through the guard and runs on a private in-memory DuckDB connection. Before the model is called, the service attaches the export read-only, copies only the rows of `course_ids` into plain tables, and detaches it, so rows of other courses never exist on that connection. External access is then disabled and the configuration locked, with `DUCKDB_MEMORY_LIMIT` (default 512MB), `DUCKDB_THREADS` (default 2) and no spilling to disk (`DUCKDB_MAX_TEMP_SIZE`, default 0B). The connection is writable, but only its own copy: a statement that got past the guard could not change the export.
4. If the guard or DuckDB rejects it, the model gets one more turn with the failed SQL and the error message, cut to 300 characters.

## Limits and timeouts

| Setting | Default | Effect |
|---|---|---|
| `ASK_CONCURRENCY` | 2 | Questions answered at the same time. Request number `ASK_CONCURRENCY + 1` gets 503 `busy` instead of waiting. |
| `DUCKDB_MEMORY_LIMIT` | 512MB | Per request connection. The DuckDB memory of `/ask` peaks at `ASK_CONCURRENCY x DUCKDB_MEMORY_LIMIT` (1 GB with the defaults), on top of the Python process. |
| `OLLAMA_TIMEOUT_S` | 150 | Seconds for all model calls of one question, counted from the start of the request. The retry only gets what the first attempt left; with less than 1 s left the answer is 504 `timeout`. |
| plugin `timeout` | 180 | Moodle's curl timeout. It is higher than `OLLAMA_TIMEOUT_S`, so the service normally gives up first and the user sees why. The proxy allows 300 s. |

The worst case is `OLLAMA_TIMEOUT_S` plus one 30 s query, which can reach the plugin timeout. Moodle then shows the same timeout message.

Each request logs one line at INFO with `user_ref`, the number of courses, attempts, elapsed time and outcome. The question text is logged only at DEBUG.

## Other endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | none | `{"status": "ok"}` (200) once an export exists, `{"status": "starting"}` (503) before. Used by the container healthcheck. |
| `GET /health` | same headers as `/ask` | Sending either header asks for the details: last export time, source, row counts and whether an export is running. A missing or wrong signature gets 401. |
| `GET /schema` | same headers as `/ask` | The model-facing schema with comments (`?format=text` for the prompt text). 401 without a valid signature. |
| `POST /refresh` | same headers as `/ask` | Runs an export now. Sign the raw body exactly as for `/ask`; the body is usually empty, so the signed message is `timestamp + "\n"`. 409 when an export is already running. |

For the signed `GET` calls the body is empty, so the signed message is `timestamp + "\n"`, as for `/refresh`. The query string is not signed. `make export` does not use HTTP: it runs the exporter inside the container.

The service exports on every start, not only when the file is missing, and retries every 5 s, doubling up to 60 s, until the first export succeeds (on a fresh stack Moodle may still be installing). A run that takes longer than `EXPORT_TIMEOUT_S` (default 600 s) is cancelled and logged as failed; the previous file keeps being served.

## Ollama in compose

- `ollama` (profile `cpu`, the default) or `ollama-gpu` (profile `gpu`, NVIDIA, `make up OLLAMA_PROFILE=gpu`). Both are only on `backend`, which has no internet access, and both answer as `ollama`. The GPU profile has not been tested: the development machine has no NVIDIA GPU.
- `make init-model` runs `model-init` (profile `init`), the only Ollama container attached to the `egress` network. It pulls `OLLAMA_MODEL` into the `ollama_models` volume and exits.
- `make clean` deletes that volume too, so the model has to be pulled again.
