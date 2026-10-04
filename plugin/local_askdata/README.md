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
| `timeout` | 60 | Seconds. The connect timeout is fixed at 5 seconds. |
| `maxrows` | 200 | Sent as `max_rows`. The service applies the lower of this and its own limit. Moodle also cuts the rows and sets `truncated`. |

From the CLI (run from the Moodle root, `/var/www/html` in the stack):

```
php public/admin/cli/cfg.php --component=local_askdata --name=serviceurl --set=http://analytics:8000
php public/admin/cli/cfg.php --component=local_askdata --name=sharedsecret --set="$ASKDATA_SHARED_SECRET"
```

### cURL security settings

Moodle checks every outgoing request against "cURL blocked hosts list" (`curlsecurityblockedhosts`) and "cURL allowed ports" (`curlsecurityallowedport`). A blocked request never leaves Moodle and the user sees "The analytics service is not reachable right now". For the stack:

- the analytics host (`analytics`, or its private IP range) must not be in `curlsecurityblockedhosts`. The default list blocks 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12 and 192.168.0.0/16, which covers Docker networks. Remove the range the service lives in.
- `curlsecurityallowedport` must include `8000`, or be empty (all ports allowed). The default list only has 443 and 80.

```
php public/admin/cli/cfg.php --name=curlsecurityallowedport --set="$(printf '443\n80\n8000')"
php public/admin/cli/cfg.php --name=curlsecurityblockedhosts --set="$(printf '127.0.0.0/8\n192.168.0.0/16\n10.0.0.0/8\n0.0.0.0\nlocalhost\n169.254.169.254\n0000::1')"
```

The second line is the core default minus `172.16.0.0/12`. Adjust it to your network.

## Security model

- The browser only calls Moodle (`local_askdata_ask`, AJAX, login required). Moodle calls the analytics service from the server with `\curl`. The service URL and secret never reach the browser.
- Each request carries `X-Askdata-Timestamp` (Unix seconds) and `X-Askdata-Signature`, the hex HMAC-SHA256 of `timestamp + "\n" + raw body` with the shared secret. The service rejects signatures older or newer than 300 seconds and replays inside that window.
- The capability is checked in the course context before anything is sent.
- `course_ids` lists every course where the user holds `local/askdata:ask` (`get_user_capability_course(..., doanything = false)`), plus the current course. A teacher in DA101 and STAT201 can only get answers about those two. Site administrators without a course role only get the current course.
- No names, emails or usernames leave Moodle. The user is sent as `user_ref`, an HMAC-SHA256 of the user id with the shared secret.
- Error responses from the service are reduced to their `message` (4xx only, plain text, at most 300 characters). 5xx bodies and transport errors are replaced by a generic message.
- Every question is logged as `\local_askdata\event\question_asked` (course context) with the question, the course ids, the elapsed time and whether it succeeded.

Request body:

```json
{"question": "...", "course_ids": [2, 3], "user_ref": "<hex>", "max_rows": 200}
```

Expected success response: `{"sql": "...", "columns": [...], "rows": [[...]], "elapsed_ms": 1234}`. Errors: any 4xx or 5xx with `{"detail": {"reason": "...", "message": "..."}}` or `{"detail": "..."}`. A 401 or 403 is shown as a signature problem.

## Running the PHPUnit tests in the stack

The stack image runs `composer install --no-dev`, so PHPUnit is not installed. Inside the moodle container, from `/var/www/html`:

1. Add the PHPUnit settings to `config.php`, before the `require_once` of `lib/setup.php`:

   ```php
   $CFG->phpunit_prefix = 'phpu_';
   $CFG->phpunit_dataroot = '/var/www/phpunitdata';
   ```

2. Install the dev dependencies and initialise the test site:

   ```
   mkdir -p /var/www/phpunitdata && chown www-data:www-data /var/www/phpunitdata
   composer install --working-dir=/var/www/html --no-interaction --no-progress
   php public/admin/tool/phpunit/cli/init.php
   ```

3. Run the plugin tests:

   ```
   vendor/bin/phpunit --testsuite local_askdata_testsuite
   ```

   `vendor/bin/phpunit public/local/askdata/tests` also works.

The tests never call the network. `\local_askdata\local\client::set_test_response()` replaces the HTTP call, and it is ignored outside PHPUnit.

## Building the JavaScript

`amd/build/chat.min.js` and its source map are committed. After editing `amd/src/chat.js`, rebuild from a Moodle checkout with `npx grunt amd --root=public/local/askdata`.
