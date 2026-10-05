# Security model

What the stack enforces today, and where it stops. `make smoke` (`scripts/smoke.sh`) and the test suites check these statements, except the known limits.

## Networks

| Network | Internal | Members |
|---|---|---|
| `frontend` | no | proxy |
| `web` | yes | proxy, moodle |
| `backend` | yes | db, moodle, cron, analytics, ollama |
| `egress` | no | model-init (one-shot, profile `init`) |

Docker publishes ports only on non-internal networks, so a Moodle with a published port would also have a route to the internet. The nginx `proxy` takes the port (`127.0.0.1:${MOODLE_PORT}`, loopback only) and forwards to Moodle over `web`. Moodle, cron, db, analytics and Ollama sit only on internal networks: DNS and direct IP connections to the internet fail from each of them, and the smoke test proves it with a positive control (internal DNS and TCP work from the same container).

`make init-model` downloads the model from `model-init`, the only container on `egress`; it is never attached to `backend`.

## Two-layer scoping

1. **Moodle** computes the course ids from the user's capability `local/askdata:ask` (editing teachers and managers by default), minus suspended or expired enrolments and hidden courses the user cannot see. Students are refused on the page and on the AJAX call.

   The scope is every course where the user holds the capability, not only the course page the question was asked from. A teacher of three courses can ask about all three from any of them. A manager assigned at system level holds the capability in every course, so the manager's questions run over the whole site. Restrict the capability (or the manager role) if that is too broad.
2. **Analytics** treats `course_ids` as the only scope. Before the model is called it copies only the rows of those courses into a private in-memory DuckDB connection and detaches the export. Rows of other courses do not exist on that connection.

## SQL guard

The guard (`analytics/app/guard.py`, sqlglot, DuckDB dialect) runs on every generated query:

- one statement, read-only root (SELECT, WITH, set operations); DDL, DML, `ATTACH`, `COPY`, `INSTALL`, `PRAGMA`, `SET` and similar are rejected;
- tables must be bare view names from the allowed list; qualified names such as `base.course`, system schemas and unknown tables are rejected;
- file, network and introspection functions are denied by name and prefix (`read_*`, `duckdb_*`, `pragma_*`, `mysql_*`, `getenv`, `glob`, ...); only `range`, `generate_series` and `unnest` are allowed as table functions;
- a row cap is added to the query.

The guard does not inspect string literals. That is why it is only the first layer.

## DuckDB settings

On the request connection: `memory_limit` (default 512MB), `threads` (default 2), `max_temp_directory_size` 0B (no spilling), then `enable_external_access = false` and `lock_configuration = true`. The connection is writable but private and in memory, so a statement that slipped past the guard could not change the export. The query has a 30 s timeout.

## Authentication between Moodle and analytics

Each request carries `X-Askdata-Timestamp` and `X-Askdata-Signature = HMAC-SHA256(secret, METHOD + "\n" + PATH + "\n" + timestamp + "\n" + body)`. The service verifies the signature over the raw bytes before parsing JSON, compares in constant time, and rejects timestamps outside `ASKDATA_REPLAY_WINDOW_S` (300 s). The method and path are part of the signed message, so a signature captured on one endpoint (say `GET /health`) is rejected on another (`POST /refresh`). Malformed headers get 401 before any comparison, and bodies over 64 KiB get 413 before they are read. An empty secret disables the endpoints (503). `/refresh`, `/schema` and the detailed `/health` use the same scheme; only the bare `/health` liveness answer (`{"status": "ok"}`) is open, for the container healthcheck. The secret stays server side: Moodle calls the service from PHP, never from the browser.

`ASK_CONCURRENCY` (default 2) caps the questions running at once, which also caps DuckDB memory at `ASK_CONCURRENCY x DUCKDB_MEMORY_LIMIT`. Extra requests get 503 `busy` straight away. The Moodle web service runs with a read-only session, so a teacher waiting for an answer does not block their other Moodle tabs.

## Database grants

The exporter connects as `analytics_ro`, which has column-level `SELECT` on exactly the columns listed in `docker/db/analytics-tables.txt`. `mdl_user.password`, emails, names, IPs and every other table are denied (MySQL 1142/1143). A one-shot `db-grants` service revokes and re-applies the grants on every `make up`. The analytics container never receives the MySQL root or Moodle passwords.

## Pseudonymisation

`user_ref = sha256(CAST(userid AS VARCHAR) || ANALYTICS_SALT)`. The views contain no names, emails or usernames. Limits: Moodle ids are small consecutive integers, so anyone who has the salt can recompute every `user_ref` in milliseconds. This is pseudonymisation, not anonymisation: it separates identities from analytics results, it does not survive a leak of the salt. Moodle also derives a separate `user_ref` for logging with an HMAC of the user id under the shared secret.

## What is logged

- analytics: one INFO line per `/ask` with `user_ref`, number of courses, attempts, elapsed time and outcome. The question text is logged only at DEBUG.
- Moodle: every question that passes the capability check, including failed ones, is logged as `\local_askdata\event\question_asked`. The full question text is stored in `logstore_standard_log`.
- The IP address Moodle stores in its logs is the proxy's address on `web`, not the browser's. nginx sends `X-Forwarded-For`, but Moodle ignores it: `getremoteaddrconf` is at its default (3, skip `X-Forwarded-For` and `Client-IP`). Change it in Site administration > Server > HTTP if per-user IPs matter, and only behind a proxy you control.
- Error messages shown to users never contain stack traces, secrets or signatures. 5xx errors map to fixed messages.

## Secrets

`.env` is generated by `scripts/gen-env.sh` with random values, is not tracked, and `make env` refuses placeholder values.

## Verifying

`make smoke` runs everything above against the live stack (SKIP means a check could not run, e.g. model not loaded). The network part also exists as a host-side test: `STACK_SMOKE=1 analytics/.venv/bin/pytest analytics/tests/test_isolation.py`. It needs the docker CLI, so `make test` leaves it out of the container run.

## Known limits

- **The proxy has egress.** It sits on `frontend`. It only forwards to Moodle, but a compromise of the proxy would have a route out. Moodle itself has none.
- **Moodle admins can change cURL security.** The configure script allows only `BACKEND_SUBNET` and port 8000, but an administrator can edit those settings in the UI and open other targets.
- **Bare `/health` is unauthenticated.** It only says whether an export exists. The details and `/schema` need a signature.
- **Replay inside the window.** A captured signed request can be replayed on the same method and path for up to 300 s (`ASKDATA_REPLAY_WINDOW_S`). Replay across endpoints is closed. There is no nonce store, so the service cannot tell a replay from a repeated question. Traffic stays on the internal `backend` network, so capturing a request already requires access to that network.
- **Scope follows the capability.** A user with `local/askdata:ask` at system or category level (managers by default) gets every course in that context.
- **Course ids are trusted.** Whoever holds the shared secret can sign any set of ids.
- **Denylist guard.** Review it when DuckDB is upgraded. The connection settings are the backstop.
