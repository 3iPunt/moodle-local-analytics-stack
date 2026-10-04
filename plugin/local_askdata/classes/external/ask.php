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

namespace local_askdata\external;

use core_external\external_api;
use core_external\external_function_parameters;
use core_external\external_multiple_structure;
use core_external\external_single_structure;
use core_external\external_value;
use local_askdata\event\question_asked;
use local_askdata\local\client;
use local_askdata\local\course_scope;

/**
 * External function local_askdata_ask.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class ask extends external_api {
    /** @var int Maximum question length in characters. */
    public const MAX_QUESTION_LENGTH = 2000;

    /** @var client|null Client override used by unit tests. */
    protected static ?client $clientoverride = null;

    /**
     * Describes the parameters.
     *
     * @return external_function_parameters
     */
    public static function execute_parameters(): external_function_parameters {
        return new external_function_parameters([
            'courseid' => new external_value(PARAM_INT, 'The current course id'),
            'question' => new external_value(PARAM_TEXT, 'The natural-language question, up to 2000 characters'),
        ]);
    }

    /**
     * Sends the question to the analytics service and returns the answer.
     *
     * @param int $courseid The current course id.
     * @param string $question The question.
     * @return array
     */
    public static function execute(int $courseid, string $question): array {
        global $USER;

        [
            'courseid' => $courseid,
            'question' => $question,
        ] = self::validate_parameters(self::execute_parameters(), [
            'courseid' => $courseid,
            'question' => $question,
        ]);

        $context = \context_course::instance($courseid);
        self::validate_context($context);
        require_capability('local/askdata:ask', $context);

        $start = microtime(true);
        $courseids = [$courseid];
        $result = null;
        // Every question that passed the capability check is audited, whatever goes wrong afterwards.
        try {
            $question = trim($question);
            if ($question === '') {
                throw new \invalid_parameter_exception('The question must not be empty.');
            }
            if (\core_text::strlen($question) > self::MAX_QUESTION_LENGTH) {
                throw new \invalid_parameter_exception('The question must not exceed ' . self::MAX_QUESTION_LENGTH . ' characters.');
            }

            $courseids = course_scope::for_user((int) $USER->id);
            if (!in_array($courseid, $courseids, true)) {
                // The capability was checked above. This covers site administrators without a course role.
                $courseids[] = $courseid;
                sort($courseids);
            }

            $client = self::$clientoverride ?? client::from_config();
            $result = $client->ask($question, $courseids, (int) $USER->id);
            return $result;
        } finally {
            $elapsed = $result['elapsed_ms'] ?? (int) round((microtime(true) - $start) * 1000);
            question_asked::create([
                'context' => $context,
                'courseid' => $courseid,
                'other' => [
                    'question' => \core_text::substr($question, 0, self::MAX_QUESTION_LENGTH),
                    'courseids' => $courseids,
                    'elapsed_ms' => (int) $elapsed,
                    'ok' => $result !== null,
                ],
            ])->trigger();
        }
    }

    /**
     * Describes the return value.
     *
     * @return external_single_structure
     */
    public static function execute_returns(): external_single_structure {
        return new external_single_structure([
            'sql' => new external_value(PARAM_RAW, 'The SQL the service ran'),
            'columns' => new external_multiple_structure(
                new external_value(PARAM_RAW, 'Column name')
            ),
            'rows' => new external_multiple_structure(
                new external_multiple_structure(
                    new external_value(PARAM_RAW, 'Cell value as a string')
                )
            ),
            'elapsed_ms' => new external_value(PARAM_INT, 'Elapsed time in milliseconds'),
            'truncated' => new external_value(PARAM_BOOL, 'Whether the rows were cut at the maximum'),
        ]);
    }

    /**
     * Replaces the HTTP client. Only for unit tests.
     *
     * @param client|null $client The client, or null to restore the default.
     */
    public static function set_client_for_testing(?client $client): void {
        if (!defined('PHPUNIT_TEST') || !PHPUNIT_TEST) {
            throw new \coding_exception('set_client_for_testing() is only available in unit tests.');
        }
        self::$clientoverride = $client;
    }
}
