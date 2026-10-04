<?php
// This file is part of Moodle - https://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// Moodle is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Moodle.  If not, see <https://www.gnu.org/licenses/>.

/**
 * English strings for local_askdata.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

$string['askdata:ask'] = 'Ask questions about course data';
$string['askyourdata'] = 'Ask your data';
$string['elapsed'] = '{$a} ms';
$string['error_badresponse'] = 'The analytics service sent an answer that could not be read. Please try again.';
$string['error_emptyquestion'] = 'Type a question first.';
$string['error_notconfigured'] = 'The analytics service is not configured yet. Ask the site administrator to set the service URL and the shared secret.';
$string['error_service'] = 'The analytics service could not answer this question: {$a}';
$string['error_service_generic'] = 'The analytics service could not answer this question. Please try again or rephrase it.';
$string['error_signature'] = 'Moodle and the analytics service could not verify each other. Ask the site administrator to check the shared secret and the server clocks.';
$string['error_unreachable'] = 'The analytics service is not reachable right now. Please try again later.';
$string['eventquestionasked'] = 'Question asked to the analytics service';
$string['example1'] = 'Which courses do I teach, and how many students are in each?';
$string['example2'] = 'Which students have not logged in for 14 days?';
$string['example3'] = 'Who has not submitted the assignment due this week?';
$string['example4'] = 'What is the average grade for each graded item in my course?';
$string['example5'] = 'Which activity has the highest drop-off?';
$string['example6'] = 'Compare completion across my courses and explain the differences';
$string['examples'] = 'Try one of these questions';
$string['history'] = 'Previous questions';
$string['intro'] = 'Ask a question in plain language about the courses you teach. The answer is computed on this organisation\'s own servers, using pseudonymised data only.';
$string['maxrows'] = 'Maximum rows';
$string['maxrows_desc'] = 'Maximum number of rows to request from the analytics service and show in an answer. The service applies the lower of this value and its own limit.';
$string['noresults'] = 'The query ran but returned no rows.';
$string['pluginname'] = 'Ask your data';
$string['privacy:metadata:analytics_service'] = 'Questions are sent to the analytics service configured by the site administrator, which runs on the organisation\'s own infrastructure. No names or email addresses are sent.';
$string['privacy:metadata:analytics_service:course_ids'] = 'The ids of the courses the user can analyse, used to limit the answer to those courses.';
$string['privacy:metadata:analytics_service:question'] = 'The question typed by the user.';
$string['privacy:metadata:analytics_service:user_ref'] = 'A pseudonymous reference derived from the user id with a keyed hash. It cannot be turned back into the user id without the shared secret.';
$string['question'] = 'Your question';
$string['questionplaceholder'] = 'For example: which students have not logged in for 14 days?';
$string['rowcount'] = '{$a} rows';
$string['send'] = 'Send';
$string['sending'] = 'Thinking...';
$string['serviceurl'] = 'Analytics service URL';
$string['serviceurl_desc'] = 'Base URL of the analytics service, without the /ask path. Moodle calls it from the server, never from the browser. Make sure the host is not in "cURL blocked hosts list" and that its port is in "cURL allowed ports".';
$string['sharedsecret'] = 'Shared secret';
$string['sharedsecret_desc'] = 'Secret shared with the analytics service. It signs every request (HMAC-SHA256) and derives the pseudonymous user reference. It must match ASKDATA_SHARED_SECRET on the service.';
$string['sql'] = 'Generated SQL';
$string['timeout'] = 'Timeout (seconds)';
$string['timeout_desc'] = 'Maximum time to wait for an answer. Local models can take a while on the first question.';
$string['truncated'] = 'Only the first {$a} rows are shown.';
