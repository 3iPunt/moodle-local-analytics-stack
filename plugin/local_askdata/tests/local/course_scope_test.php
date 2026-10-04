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
 * Tests for the course scope helper.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
#[\PHPUnit\Framework\Attributes\CoversClass(course_scope::class)]
final class course_scope_test extends \advanced_testcase {
    /**
     * A teacher in two of three courses gets exactly those two course ids.
     */
    public function test_teacher_gets_only_taught_courses(): void {
        $this->resetAfterTest();
        $gen = $this->getDataGenerator();
        $c1 = $gen->create_course();
        $c2 = $gen->create_course();
        $c3 = $gen->create_course();
        $teacher = $gen->create_user();
        $gen->enrol_user($teacher->id, $c1->id, 'editingteacher');
        $gen->enrol_user($teacher->id, $c2->id, 'editingteacher');
        $gen->enrol_user($teacher->id, $c3->id, 'student');

        $expected = [(int) $c1->id, (int) $c2->id];
        sort($expected);
        $this->assertSame($expected, course_scope::for_user((int) $teacher->id));
    }

    /**
     * A student gets no courses.
     */
    public function test_student_gets_nothing(): void {
        $this->resetAfterTest();
        $gen = $this->getDataGenerator();
        $student = $gen->create_user();
        foreach ([1, 2, 3] as $unused) {
            $gen->enrol_user($student->id, $gen->create_course()->id, 'student');
        }
        $this->assertSame([], course_scope::for_user((int) $student->id));
    }

    /**
     * A non-editing teacher does not get the capability by default.
     */
    public function test_noneditingteacher_gets_nothing(): void {
        $this->resetAfterTest();
        $gen = $this->getDataGenerator();
        $user = $gen->create_user();
        $gen->enrol_user($user->id, $gen->create_course()->id, 'teacher');
        $this->assertSame([], course_scope::for_user((int) $user->id));
    }
}
