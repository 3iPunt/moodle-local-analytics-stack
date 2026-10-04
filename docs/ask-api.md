# /ask API

`POST http://analytics:8000/ask`, reachable only on the internal `backend` network. The Moodle plugin (`local_askdata`) and `make ask` use it.

## Authentication

Every request is signed with the shared secret `ASKDATA_SHARED_SECRET`.

| Header | Value |
|---|---|
| `X-Askdata-Timestamp` | Unix time in seconds |
| `X-Askdata-Signature` | Lowercase hex of `HMAC-SHA256(secret, timestamp + "\n" + body)` |

`body` is the exact byte string sent as the request body. The service checks the signature over the raw bytes before it parses the JSON, so the client must sign the same bytes it sends. PHP:

```php
$body = json_encode($payload);
$ts = (string) time();
$sig = hash_hmac('sha256', $ts . "\n" . $body, $secret);
```

Requests older or newer than `ASKDATA_REPLAY_WINDOW_S` (default 300 s) are rejected. When `ASKDATA_SHARED_SECRET` is empty the endpoint answers 503 to everything.

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
| 401 | `bad_signature` | Signature does not match, or the timestamp is not an integer |
| 503 | `not_configured` | `ASKDATA_SHARED_SECRET` is empty |
| 422 | (validation list) | Body does not match the rules above |
| 422 | `sql_rejected` | The guard rejected the SQL twice. `detail.sql` has the last attempt. |
| 422 | `sql_error` | DuckDB rejected the SQL twice. `detail.sql` has the last attempt. |
| 502 | `model_unavailable` | Ollama is down, the model is not pulled, or the runner died (for example out of memory) |
| 504 | `timeout` | The model (`OLLAMA_TIMEOUT_S`) or the query (30 s) took too long |

## How a question is answered

1. The prompt starts with fixed rules and the schema, the same for every request, so Ollama reuses that part of its KV cache.
2. Then come the `EXAMPLES_TOP_K` examples from `analytics/examples.yaml` whose words overlap most with the question (Jaccard over word sets), closest one last.
3. Ollama answers with `temperature` 0 and `num_ctx` `OLLAMA_NUM_CTX`. The SQL goes through the guard and runs on a read-only DuckDB connection whose views contain only `course_ids`.
4. If the guard or DuckDB rejects it, the model gets one more turn with the failed SQL and the error message.

Each request logs one line at INFO with `user_ref`, the number of courses, attempts, elapsed time and outcome. The question text is logged only at DEBUG.

## Ollama in compose

- `ollama` (profile `cpu`, the default) or `ollama-gpu` (profile `gpu`, NVIDIA, `make up OLLAMA_PROFILE=gpu`). Both are only on `backend`, which has no internet access, and both answer as `ollama`. The GPU profile has not been tested: the development machine has no NVIDIA GPU.
- `make init-model` runs `model-init` (profile `init`), the only Ollama container attached to the `egress` network. It pulls `OLLAMA_MODEL` into the `ollama_models` volume and exits.
- `make clean` deletes that volume too, so the model has to be pulled again.
