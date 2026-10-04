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

namespace local_askdata\output;

use core\output\named_templatable;
use core\output\renderable;
use core\output\renderer_base;

/**
 * Renderable for the "Ask your data" chat page.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class chat_page implements renderable, named_templatable {
    /** @var int Number of example questions defined in the language pack. */
    public const EXAMPLE_COUNT = 6;

    /**
     * Constructor.
     *
     * @param \stdClass $course The current course.
     * @param \context_course $context The course context.
     */
    public function __construct(
        /** @var \stdClass The current course. */
        protected \stdClass $course,
        /** @var \context_course The course context. */
        protected \context_course $context,
    ) {
    }

    /**
     * Exports the data for the chat template.
     *
     * @param renderer_base $output The renderer.
     * @return array
     */
    public function export_for_template(renderer_base $output): array {
        $examples = [];
        for ($i = 1; $i <= self::EXAMPLE_COUNT; $i++) {
            $examples[] = ['text' => get_string('example' . $i, 'local_askdata')];
        }
        return [
            'courseid' => (int) $this->course->id,
            'coursefullname' => format_string($this->course->fullname, true, ['context' => $this->context]),
            'examples' => $examples,
            'hasexamples' => !empty($examples),
            'maxlength' => \local_askdata\external\ask::MAX_QUESTION_LENGTH,
        ];
    }

    /**
     * Returns the template used to render this page.
     *
     * @param renderer_base $renderer The renderer.
     * @return string
     */
    public function get_template_name(renderer_base $renderer): string {
        return 'local_askdata/chat';
    }
}
