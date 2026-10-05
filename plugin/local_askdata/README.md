# Ask your data (local_askdata)

Teachers type a question in plain language on a course page and get back a table, the SQL that produced it and the time it took. Moodle forwards the question to the analytics service of the demo stack (`POST {serviceurl}/ask`). The service writes the SQL with a local model and runs it on pseudonymised views.

Requires Moodle 5.1 or later and PHP 8.2 or later.

## Where it shows up

Course page, "More" menu, "Ask your data" (`/local/askdata/index.php?courseid=N`). Only users with `local/askdata:ask` in that course see the link. By default that is editing teachers and managers. Students and non-editing teachers do not get it.

## Settings

Site administration > Plugins > Local plugins > Ask your data.

| Setting | Default | Notes |
|---|---|---|
| `serviceurl` | `http://analytics:8000` | Base URL, without `/ask`. |
| `sharedsecret` | empty | Must match `ASKDATA_SHARED_SECRET` on the service. The plugin refuses to call the service while it is empty. |
| `timeout` | 180 | Seconds. Keep it above `OLLAMA_TIMEOUT_S` on the service (150), so the service gives up first. The connect timeout is fixed at 5 seconds. Sites upgraded from the old 60 s default move to 180. |
| `maxrows` | 200 | Sent as `max_rows`. The service applies the lower of this and its own limit. Moodle also cuts the rows and sets `truncated`. |

From the CLI (run from the Moodle root, `/var/www/html` in the stack):

```
php public/admin/cli/cfg.php --component=local_askdata --name=serviceurl --set=http://analytics:8000
php public/admin/cli/cfg.php --component=local_askdata --name=sharedsecret --set="$ASKDATA_SHARED_SECRET"
```

### cURL security settings

Moodle checks every outgoing request against "cURL blocked hosts list" (`curlsecurityblockedhosts`) and "cURL allowed ports" (`curlsecurityallowedport`). A blocked request never leaves Moodle and the user sees "The analytics service is not reachable right now". The default lists block every private range (Docker networks included) and only allow ports 443 and 80, so the plugin cannot reach `http://analytics:8000` out of the box.

Do not remove `172.16.0.0/12` (or any other private range) from the blocked list: that would let Moodle reach every container and host service in that range. In the demo stack, `scripts/moodle/configure-askdata.sh` (`make configure-plugin`, also run by the container on start) changes exactly this:

- `curlsecurityallowedport`: `443`, `80` and the service port (`8000`).
- `curlsecurityblockedhosts`: Moodle's default list, except that the private range holding `BACKEND_SUBNET` is replaced by its exact complement. Only the backend subnet (default `172.28.0.0/24`) becomes reachable; the rest of `172.16.0.0/12` stays blocked.

Run it with `--dry-run` to see the values without changing anything. Outside the stack, apply the same idea: unblock only the subnet or host where the service runs.

## Security model

- The browser only calls Moodle (`local_askdata_ask`, AJAX, login required). Moodle calls the analytics service from the server with `\curl`. The service URL and secret never reach the browser.
- Each request carries `X-Askdata-Timestamp` (Unix seconds) and `X-Askdata-Signature`, the hex HMAC-SHA256 of `METHOD + "\n" + PATH + "\n" + timestamp + "\n" + raw body` (`POST` and the path of the `/ask` URL) with the shared secret. The service rejects signatures older or newer than 300 seconds and replays inside that window.
- `local_askdata_ask` declares `readonlysession` so a slow model answer does not block the user's other requests. Moodle only honours it when `$CFG->enable_read_only_sessions = true` is set in `config.php`; the stack's entrypoint sets it. Elsewhere, set it yourself and map session-mode caches to a store other than `default_session` (Site administration > Plugins > Caching > Configuration), or every login fails with "The session caches can not be in the session store".
- The capability is checked in the course context before anything is sent.
- `course_ids` lists every course where the user holds `local/askdata:ask` (`get_user_capability_course(..., doanything = false)`), plus the current course. Courses where the user's enrolment is suspended or expired are left out, and so are hidden courses unless the user can see hidden courses (`moodle/course:viewhiddencourses`). Category or system roles without an enrolment (managers) still count. A teacher in DA101 and STAT201 can only get answers about those two. Site administrators without a course role only get the current course.
- No names, emails or usernames leave Moodle. The user is sent as `user_ref`, an HMAC-SHA256 of the user id with the shared secret.
- Error responses from the service are reduced to their `message` (4xx only, plain text, at most 300 characters). 5xx bodies and transport errors are replaced by a generic message.
- Every question that passes the capability check is logged as `\local_askdata\event\question_asked` (course context), including failed ones (invalid question, plugin not configured, service errors). The event stores the full question text in the Moodle log (`logstore_standard_log.other`), together with the course ids, the elapsed time and whether an answer came back. Anyone who can read the course logs can read the questions, and they are kept as long as the log retention setting says. Privacy requests export and delete them with the user's other log entries (the log store's privacy provider).

Request body:

```json
{"question": "...", "course_ids": [2, 3], "user_ref": "<hex>", "max_rows": 200}
```

Expected success response: `{"sql": "...", "columns": [...], "rows": [[...]], "elapsed_ms": 1234}`. Errors: any 4xx or 5xx with `{"detail": {"reason": "...", "message": "..."}}` or `{"detail": "..."}`. A 401 or 403 is shown as a signature problem.

## Running the PHPUnit tests in the stack

The stack image installs Composer dev dependencies and its `config.php` sets `phpunit_prefix = 'phpu_'` and `phpunit_dataroot = '/var/www/phpunitdata'`. From the repository root:

```
make test-plugin
```

It initialises the PHPUnit site on the first run (`admin/tool/phpunit/cli/init.php`, a few minutes) and then runs `vendor/bin/phpunit --testsuite local_askdata_testsuite` as `www-data` inside the moodle container.

The tests never call the network. `\local_askdata\local\client::set_test_response()` replaces the HTTP call, and it is ignored outside PHPUnit.

## Building the JavaScript

`amd/build/chat.min.js` and its source map are committed. After editing `amd/src/chat.js`, rebuild from a Moodle checkout with `npx grunt amd --root=public/local/askdata`.
