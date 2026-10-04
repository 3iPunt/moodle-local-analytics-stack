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

namespace local_askdata\event;

/**
 * Event triggered when a user asks the analytics service a question.
 *
 * @property-read array $other {
 *      Extra information about the event.
 *
 *      - string question: The question as typed by the user.
 *      - int[] courseids: The courses the answer was scoped to.
 *      - int elapsed_ms: Round trip time in milliseconds.
 *      - bool ok: Whether the service returned an answer.
 * }
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class question_asked extends \core\event\base {
    /**
     * Initialises the event data.
     */
    protected function init() {
        $this->data['crud'] = 'r';
        $this->data['edulevel'] = self::LEVEL_TEACHING;
    }

    /**
     * Returns the localised event name.
     *
     * @return string
     */
    public static function get_name() {
        return get_string('eventquestionasked', 'local_askdata');
    }

    /**
     * Returns a non-localised description of the event.
     *
     * @return string
     */
    public function get_description() {
        $status = !empty($this->other['ok']) ? 'got an answer' : 'did not get an answer';
        $count = count($this->other['courseids']);
        return "The user with id '{$this->userid}' asked the analytics service a question from the course with id " .
            "'{$this->courseid}', scoped to {$count} course(s), and {$status}.";
    }

    /**
     * Returns the URL of the "Ask your data" page for the course.
     *
     * @return \moodle_url
     */
    public function get_url() {
        return new \moodle_url('/local/askdata/index.php', ['courseid' => $this->courseid]);
    }

    /**
     * Validates the event data.
     *
     * @throws \coding_exception
     */
    protected function validate_data() {
        parent::validate_data();
        if ($this->contextlevel != CONTEXT_COURSE) {
            throw new \coding_exception('The context must be a course context.');
        }
        foreach (['question', 'courseids', 'elapsed_ms', 'ok'] as $key) {
            if (!isset($this->other[$key])) {
                throw new \coding_exception("The '{$key}' value must be set in other.");
            }
        }
        if (!is_array($this->other['courseids'])) {
            throw new \coding_exception("The 'courseids' value must be an array.");
        }
    }

    /**
     * Course ids in "other" refer to the whole scope at the time of the question and are not remapped on restore.
     *
     * @return array
     */
    public static function get_other_mapping() {
        return ['courseids' => self::NOT_MAPPED];
    }
}
