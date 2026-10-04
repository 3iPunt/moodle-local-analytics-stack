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

    /**
     * A course where the teacher's enrolment is suspended or expired is dropped.
     */
    public function test_inactive_enrolment_is_dropped(): void {
        $this->resetAfterTest();
        $gen = $this->getDataGenerator();
        $active = $gen->create_course();
        $suspended = $gen->create_course();
        $expired = $gen->create_course();
        $teacher = $gen->create_user();
        $gen->enrol_user($teacher->id, $active->id, 'editingteacher');
        $gen->enrol_user($teacher->id, $suspended->id, 'editingteacher', 'manual', 0, 0, ENROL_USER_SUSPENDED);
        $gen->enrol_user($teacher->id, $expired->id, 'editingteacher', 'manual', time() - 2 * DAYSECS, time() - DAYSECS);

        $this->assertTrue(has_capability('local/askdata:ask', \context_course::instance($suspended->id), $teacher));
        $this->assertSame([(int) $active->id], course_scope::for_user((int) $teacher->id));
    }

    /**
     * A hidden course is kept only while the user can see hidden courses.
     */
    public function test_hidden_course_requires_viewhiddencourses(): void {
        $this->resetAfterTest();
        $gen = $this->getDataGenerator();
        $visible = $gen->create_course();
        $hidden = $gen->create_course(['visible' => 0]);
        $teacher = $gen->create_user();
        $gen->enrol_user($teacher->id, $visible->id, 'editingteacher');
        $gen->enrol_user($teacher->id, $hidden->id, 'editingteacher');

        $expected = [(int) $visible->id, (int) $hidden->id];
        sort($expected);
        $this->assertSame($expected, course_scope::for_user((int) $teacher->id));

        $roleid = (int) $this->get_role_id('editingteacher');
        $hiddencontext = \context_course::instance($hidden->id);
        assign_capability('moodle/course:viewhiddencourses', CAP_PREVENT, $roleid, $hiddencontext->id, true);
        accesslib_clear_all_caches_for_unit_testing();

        $this->assertSame([(int) $visible->id], course_scope::for_user((int) $teacher->id));
    }

    /**
     * A manager assigned at category level keeps the category's courses without being enrolled.
     */
    public function test_category_manager_without_enrolment(): void {
        $this->resetAfterTest();
        $gen = $this->getDataGenerator();
        $category = $gen->create_category();
        $c1 = $gen->create_course(['category' => $category->id]);
        $c2 = $gen->create_course(['category' => $category->id]);
        $gen->create_course();
        $manager = $gen->create_user();
        role_assign($this->get_role_id('manager'), $manager->id, \context_coursecat::instance($category->id));

        $expected = [(int) $c1->id, (int) $c2->id];
        sort($expected);
        $this->assertSame($expected, course_scope::for_user((int) $manager->id));
    }

    /**
     * Returns the id of a standard role.
     *
     * @param string $shortname Role short name.
     * @return int
     */
    private function get_role_id(string $shortname): int {
        global $DB;
        return (int) $DB->get_field('role', 'id', ['shortname' => $shortname], MUST_EXIST);
    }
}
