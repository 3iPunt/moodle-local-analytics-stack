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

namespace local_askdata\local;

/**
 * Computes the courses a user may analyse.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class course_scope {
    /**
     * Returns the ids of the courses where the user holds local/askdata:ask.
     *
     * Site administrators are not granted courses implicitly ("doanything" is
     * disabled), so the scope only reflects real role assignments.
     *
     * @param int $userid The user id.
     * @return int[] Sorted course ids, without the site course.
     */
    public static function for_user(int $userid): array {
        $courses = get_user_capability_course('local/askdata:ask', $userid, false);
        if (empty($courses)) {
            return [];
        }
        $ids = [];
        foreach ($courses as $course) {
            $id = (int) $course->id;
            if ($id !== SITEID) {
                $ids[$id] = $id;
            }
        }
        sort($ids);
        return array_values($ids);
    }
}
