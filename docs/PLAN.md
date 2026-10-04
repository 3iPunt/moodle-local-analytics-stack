# Plan: Moodle local analytics stack

Demo for the talk "Your data, your infrastructure: local AI and open-source analytics for Moodle".

## Promises to prove

1. Export Moodle data to DuckDB (optionally Parquet).
2. A local Ollama model writes SQL from natural-language questions.
3. Free exploration over curated, pseudonymised views.
4. Nothing leaves the infrastructure at runtime.

## Pinned versions (verified 2026-10-04)

| Component | Version | Reason |
|---|---|---|
| Moodle | `v5.3.0` (env `MOODLE_VERSION`) | Latest stable 5.x tag. Plugin requires Moodle 5.1+. |
| PHP image | `moodlehq/moodle-php-apache:8.3-bookworm@sha256:501f19fa…` | Moodle 5.2/5.3 require PHP 8.3; 5.1 accepts 8.2-8.4. arm64 + amd64. Pinned by index digest (full value in `docker/moodle/Dockerfile`). |
| Proxy | `nginx:1.30.5-alpine` | Stable branch. Only container with a published port. |
| MySQL | `mysql:8.4.11` | Moodle 5.x requires MySQL 8.4 minimum. |
| Ollama | `ollama/ollama:0.35.1` | arm64 + amd64. |
| Python | `python:3.12.15-slim` | |
| DuckDB | `1.5.6` | `mysql_scanner` extension published for linux_arm64 and linux_amd64. |
| sqlglot | `30.21.0` | SQL guard parser. |
| FastAPI | `0.142.2` | |

## Risks

1. Docker Desktop on the dev machine has 8 GB RAM (7.67 GB VM). `qwen2.5-coder:14b` needs about 9 GB. Default stays 14b in `.env.example`. Outcome: only `qwen2.5-coder:1.5b` was measured, and only with db, moodle and cron stopped; 7b and 14b were not run (see `docs/benchmark.md`).
2. No NVIDIA GPU available. The `gpu` compose profile is written but not verified.
3. Docker Compose v2.17 on the dev machine. Avoid `include` and recent syntax.
4. DuckDB `mysql_scanner` must be installed at image build time (runtime has no internet). Fallback: `pymysql` + Parquet (`EXPORT_FORMAT=parquet`).
5. Moodle generator `maketestsite` is slow. Use `maketestcourse` several times plus a custom variety script.

## Networks

| Network | Internal | Members | Purpose |
|---|---|---|---|
| `frontend` | no | proxy | Publishes `127.0.0.1:${MOODLE_PORT}`. The proxy is the only container with egress. |
| `web` | yes | proxy, moodle | Proxy to Moodle. |
| `backend` | yes, subnet `${BACKEND_SUBNET:-172.28.0.0/24}` | db, moodle, cron, analytics, ollama | Application traffic. |
| `egress` | no | model-init | One-shot model download only. |

Docker only publishes ports on non-internal networks, so Moodle cannot keep a published port without also getting a route to the internet. The nginx proxy (`docker/proxy/default.conf`) takes the published port and forwards `Host` unchanged (`$http_host`, which keeps `:8080`), so `wwwroot` stays `http://localhost:8080` and Moodle needs no reverse proxy settings. Verified 2026-10-04: moodle, cron, analytics, ollama and db time out on DNS and on a direct IP (1.1.1.1); the proxy reaches the internet, which is expected because it only forwards to Moodle.

`BACKEND_SUBNET` is pinned so Moodle's curl security can allow exactly that range. Override it in `.env` when it overlaps a network on the host (on the dev machine `172.28.0.0/16` belongs to another project, so `.env` uses `172.30.0.0/24`).

## Database access

`analytics_ro` has column-level `SELECT` on exactly the columns the exporter reads (`docker/db/analytics-tables.txt`, kept equal to `SOURCE_COLUMNS` in `analytics/app/export.py` by a unit test). `mdl_user.password`, emails, names, IPs and every other table are denied (MySQL errors 1142/1143). Both export paths work with these grants: mysql_scanner only sees the granted columns in `information_schema` and pushes the projection down.

The grants are applied by the one-shot service `db-grants` (`docker/db/analytics-grants.sh`) after Moodle is healthy and before `analytics` starts. It cannot run from `docker-entrypoint-initdb.d`: MySQL rejects a table-level grant on a table that does not exist yet (error 1146), and Moodle creates its tables later. Each run revokes everything and grants again, so stacks created before this change get the narrower grants on the next `make up`; no `make clean` is needed.

## Data model rules

- `user_ref = sha256(CAST(userid AS VARCHAR) || ANALYTICS_SALT)`, hex. The brief said md5; this deviates on purpose. Moodle user ids are small consecutive integers, so anyone who obtains the salt can hash every id in milliseconds either way, but md5 also has a much cheaper offline cost per guess. sha256 is just as deterministic and stable across exports, so joins and the plugin contract (hex `user_ref`, 8 to 128 characters) are unaffected.
- Deleted users and course modules being deleted never appear in any table (see the header of `analytics/views.sql`).
- `participant.suspended` follows Moodle's active-enrolment rule: user enrolment and enrolment method enabled, `timestart` not in the future and `timeend` not in the past, at export time.
- `participant` keeps one row per (course, user, role); counts must use `count(DISTINCT user_ref)`.

## Phases

Each phase ends with a verification run and a commit.

- (a) db + moodle + cron up and installed non-interactively.
- (b) demo data.
- (c) analytics export, DuckDB views, COMMENTs.
- (d) ollama + model-init + `/ask` end to end with the six demo questions.
- (e) `local_askdata` plugin installed and working in the UI. Done, see `docs/plugin.md`.
- (f) network isolation and SQL guard tests.
- (g) README. Done, see `README.md`.

## Layout

```
compose.yaml  .env.example  Makefile  README.md
docker/moodle/Dockerfile
analytics/   (app, export, guard, views.sql, examples.yaml, tests/)
plugin/local_askdata/
scripts/     (env generation, demo data, smoke test)
docs/
```
