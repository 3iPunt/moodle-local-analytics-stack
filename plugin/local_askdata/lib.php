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
 * Library callbacks for local_askdata.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

/**
 * Adds the "Ask your data" link to the course navigation for users with the capability.
 *
 * The node is added to the course administration tree, which the secondary
 * navigation shows under the "More" menu.
 *
 * @param navigation_node $navigation The course navigation node.
 * @param stdClass $course The course.
 * @param context_course $context The course context.
 */
function local_askdata_extend_navigation_course(navigation_node $navigation, stdClass $course, context_course $context): void {
    if ($course->id == SITEID || !has_capability('local/askdata:ask', $context)) {
        return;
    }
    $navigation->add(
        get_string('askyourdata', 'local_askdata'),
        new moodle_url('/local/askdata/index.php', ['courseid' => $course->id]),
        navigation_node::TYPE_SETTING,
        null,
        'local_askdata',
        new pix_icon('i/stats', '')
    );
}
