# Final status report

Status of the demo stack for "Your data, your infrastructure: local AI and open-source analytics for Moodle" on 2026-10-04, after phases (a) to (g) of [PLAN.md](PLAN.md).

Development machine: Apple M1 Pro, 32 GB host RAM, Docker Desktop VM limited to 7.67 GB and 5 CPUs, no NVIDIA GPU, Docker 23.0.5, Compose v2.17.3. Everything below was measured there unless it says otherwise.

## What works

- `make up` builds the images and installs Moodle v5.3.0 unattended (install 107 s, Apache serving after 127 s). The `local_askdata` plugin is installed and configured on every container start.
- `make demo-data` creates 5 courses, 100 students and 3 teachers with the patterns in [demo-data.md](demo-data.md) in 41 s. A re-run takes 3 s.
- The export to DuckDB takes 0.3 to 0.6 s; to Parquet about 0.6 s. Both formats give the same tables (tested).
- `/ask` answers the six demo questions with `qwen2.5-coder:1.5b`, all correct on the first attempt. Paraphrases: 5 of 6 correct.
- The "Ask your data" page in Moodle sends signed, course-scoped requests and shows SQL, table and time. When the model cannot load it shows a dedicated message.
- Tests: analytics 266 passed, 2 skipped. Plugin PHPUnit 32 tests, 98 assertions, about 55 s (1 min 53 s on the first run, which initialises the test site).
- `make smoke`: 57 PASS, 0 FAIL, 3 SKIP, plus 20 passed in the host-side isolation test. The three skips all come from the model not loading for lack of memory while the full stack runs.

## What could not be verified

- `qwen2.5-coder:7b` and `14b`. The Docker VM has 7.67 GB and about 1.7 GB free with the stack up. Even 1.5b was killed by the kernel while db and moodle ran, so the benchmark was taken with this project's db, moodle and cron containers stopped for a moment. In the browser on this machine, with the whole stack up, the plugin showed the "model unavailable" message.
- The `gpu` profile (`make up OLLAMA_PROFILE=gpu`). No NVIDIA GPU.
- x86_64. All images were built and run on arm64. The pinned images are multi-arch.
- The full sequence below on a clean machine in one go. Each phase was verified on its own. `make demo-reset` was only dry-run.
- The advice to give Docker Desktop about 16 GB for 7b next to the stack is an estimate.

## Commands from a clean machine

```bash
git clone <repository-url> moodle-local-stack
cd moodle-local-stack
make env
# edit OLLAMA_MODEL in .env now if the machine has less than about 9 GB for the model
make init-model     # ollama image pull about 11 min (4.2 GB), 1.5b model 95 s
make up             # Moodle image build about 1 min 53 s, then 127 s until Moodle serves
make demo-data      # 41 s
# browser: http://localhost:8080, user lmartinez, password DEMO_USER_PASSWORD from .env,
# course "Data Analysis 101", More, "Ask your data"
make ask Q="Which students have not logged in for 14 days?" COURSES=2,3,4
make bench
make smoke
make test
```

Within 3 days before the talk: `make demo-reset` (deletes Moodle, MySQL and export data, keeps the model).

## Measured answer times

Model `qwen2.5-coder:1.5b`, CPU only, Apple M1 Pro with the Docker VM above, scope course ids 2, 3, 4 (teacher lmartinez), one run each after a warm-up call of 11.6 s. Full table with the model/SQL split and the generated SQL: [benchmark.md](benchmark.md).

| # | Question | Elapsed | Correct |
|---|---|---|---|
| 1 | Which courses do I teach, and how many students are in each? | 9.0 s | yes |
| 2 | Which students have not logged in for 14 days? | 10.0 s | yes |
| 3 | Who has not submitted the assignment due this week? | 13.0 s | yes |
| 4 | What is the average grade for each graded item in my course? | 11.3 s | yes |
| 5 | Which activity has the highest drop-off? | 27.2 s | yes |
| 6 | Compare completion across my courses and explain the differences | 30.4 s | yes |

A warm repeat of a question took about 3.3 s. Almost all of the time is the model: prompt evaluation of the few-shot examples and output generation. SQL runs in 20 to 90 ms.

These six questions are also few-shot examples, so the model can copy their SQL. The paraphrase set is the fairer test: 5 of 6 correct, and the drop-off paraphrase failed after the retry (422 `sql_rejected`).

## Deviations from the brief

- nginx proxy in front of Moodle, so Moodle has no egress (Docker publishes ports only on non-internal networks).
- `user_ref = sha256(id || salt)` instead of md5.
- Column-level grants for `analytics_ro`, applied by the one-shot `db-grants` service.
- `/refresh` requires the HMAC signature.
- A second scoping layer: course-filtered tables copied into a locked in-memory DuckDB per request.
- `make clean` removes the Ollama model volume; `make demo-reset` keeps it.
- `BACKEND_SUBNET` is configurable, and `scripts/moodle/configure-askdata.sh` opens Moodle's curl security for exactly that /24.
- `/schema` and the detailed `/health` need the HMAC signature. Only the bare `/health` liveness answer is open.
- At most `ASK_CONCURRENCY` (default 2) questions run at once; the rest get 503 `busy`. `OLLAMA_TIMEOUT_S` (150 s) is a budget for both model calls of a question, below the plugin timeout (180 s).

## Commits by phase

Plan
- `467f43e` docs: add project plan with pinned versions and risks

(a) db, moodle and cron with unattended install
- `1b53c66` feat: add moodle, mysql and cron services with unattended install

(b) Demo data
- `9c216d0` feat: generate demo courses with graded, completion and activity patterns

(c) Export, views and schema
- `fc53511` feat(analytics): add SQL guard and hardened DuckDB connection
- `2bda3cf` feat(analytics): export pseudonymised Moodle subset to DuckDB with documented schema
- `f1eadc1` feat(analytics): serve health, schema and refresh API as a compose service

(d) Ollama and `/ask`
- `4b37eb0` feat: add ollama runtime, gpu profile and one-shot model-init
- `e861ef0` feat(analytics): answer natural-language questions with guarded SQL via Ollama
- `732902b` feat(analytics): add ask and bench CLI with checks against the demo facts
- `4604d4f` docs: record benchmark with qwen2.5-coder:1.5b

Hardening between (d) and (e)
- `19db8a8` feat: front Moodle with nginx so no app container has egress
- `7ba27fd` feat(analytics): copy course-scoped tables into a locked in-memory connection
- `40be567` fix(db): grant analytics user SELECT only on exported columns
- `375a6ab` fix(analytics): retry startup export and harden refresh
- `d7c69f8` test: identify demo teachers without reading usernames
- `bd9462a` test: pin demo facts to the generation time
- `b820153` fix(analytics): tighten enrolment and deletion semantics in views
- `089e399` build: pin moodle base image by digest and refuse placeholder secrets
- `6908534` feat: add script that opens Moodle curl security for the backend network

(e) `local_askdata` plugin
- `a071601` feat(plugin): add local_askdata with course-scoped ask page and signed service client
- `74dcd10` fix(plugin): restrict course scope to active enrolments and audit every failure
- `a56a616` build: install dev dependencies and wire PHPUnit for the plugin
- `f36b7ee` feat: install and configure local_askdata on container start
- `16a812f` docs: describe the local_askdata plugin
- `5982ab9` fix(build): regenerate phpunit.xml when the moodle container is recreated

(f) Isolation and guard tests
- `471d9a8` feat: add smoke test proving isolation, auth and scoping
- `01fd87d` test(analytics): add host-side network isolation test
- `31cddbe` fix(plugin): show a dedicated message when the local model is unavailable

(g) README
- `831ae5d` docs: write README with architecture, quick start and verification status

Final fixes, after the last review
- `09f357f` fix(analytics): require the signature on schema and detailed health
- `71960ac` feat(analytics): bound concurrent asks and reject oversized or malformed requests
- `0da14e0` fix(plugin): release the session during asks and report a busy service
- `0fa24eb` fix: harden grants, smoke checks, make targets and upgrade on start
- docs: document scope policy, replay window and final fixes (this report update)
