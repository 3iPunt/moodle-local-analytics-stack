# local_askdata in the stack

`plugin/local_askdata` adds an "Ask your data" page to every course (course "More" menu, `/local/askdata/index.php?courseid=N`). A teacher types a question, Moodle sends it to the analytics service (`POST http://analytics:8000/ask`, see `docs/ask-api.md`) and shows the SQL, the result table and the elapsed time. The plugin's own README (`plugin/local_askdata/README.md`) has the full details.

## Install and configuration

The image copies the plugin into `public/local/askdata`, and compose also bind-mounts `./plugin/local_askdata` read-only over that path in `moodle` and `cron`. Plugin edits show up without a rebuild; `cron` gets the mount too because it refuses to run while it sees a different plugin version than the database.

On every start the moodle entrypoint:

1. installs Moodle if the database is empty (the plugin is installed with it);
2. runs `admin/cli/upgrade.php --non-interactive`, which installs or upgrades the plugin when `version.php` changed and prints "No upgrade needed" otherwise;
3. runs `scripts/moodle/configure-askdata.sh`, which sets `local_askdata/serviceurl`, `local_askdata/sharedsecret`, `curlsecurityallowedport` and `curlsecurityblockedhosts`. It only purges caches when a value changed. If it fails (for example an empty `ASKDATA_SHARED_SECRET`) Moodle still starts and the log shows a warning.

`make configure-plugin` runs the same script on demand, and `docker compose exec -T moodle bash /opt/stack/scripts/configure-askdata.sh --dry-run` only prints the values. The values come from `.env`: `ASKDATA_SHARED_SECRET`, `ANALYTICS_URL` and `BACKEND_SUBNET`.

## Security model

- Only users with `local/askdata:ask` in the course see the link and can call `local_askdata_ask` (editing teachers and managers by default). Students get `nopermissions` on the page and on the AJAX call.
- The question is scoped to the courses where the user holds the capability, minus courses with a suspended or expired enrolment and hidden courses the user cannot see. Category managers without an enrolment keep their courses.
- Moodle signs each request with HMAC-SHA256 over `timestamp + "\n" + body` (`X-Askdata-Timestamp`, `X-Askdata-Signature`). The secret and service URL never reach the browser. The user is sent as an HMAC of the user id.
- Moodle's curl security stays on. The script unblocks only `BACKEND_SUBNET` (the rest of `172.16.0.0/12` and the other private ranges stay blocked) and adds port 8000.
- Every question that passes the capability check is logged as `\local_askdata\event\question_asked`, including failed ones. The full question text is stored in `logstore_standard_log`.

## Tests

```
make test-plugin   # PHPUnit for local_askdata
make test          # analytics pytest, then the plugin tests
```

The image installs Composer dev dependencies at build time (the container has no internet afterwards) and keeps `composer.phar` in `/var/www/html` so `init.php --disable-composer` does not try to download it. `config.php` sets `phpunit_prefix = 'phpu_'` and `phpunit_dataroot = '/var/www/phpunitdata'` (volume `phpunitdata`). The first run initialises the test site in about 80 seconds; later runs skip that step while `util.php --diag` reports it as current.

## Known limits

- The page shows the SQL and the table only. The service does not write an explanation of the answer.
- The model needs more memory than the 8 GB development machine has free while MySQL and Moodle run. On that machine `/ask` answers 502 `model_unavailable`, and the page shows a dedicated message asking the administrator to check the Ollama service. A 504, or a request that reaches the plugin `timeout` (180 s), shows a timeout message. A 503 `busy` (the service is already answering `ASK_CONCURRENCY` questions) shows "answering other questions, try again".
- The web service runs with a read-only session (`readonlysession` in `db/services.php`), so a long answer does not lock the user's other Moodle requests.
- The demo students (`tool_generator_*`) have no password. To log in as one, set it with `php admin/cli/reset_password.php --username=tool_generator_000001 --password=... --ignore-password-policy` as `www-data`.
