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

namespace local_askdata;

/**
 * Tests for the capability definition and the course navigation node.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
#[\PHPUnit\Framework\Attributes\CoversFunction('local_askdata_extend_navigation_course')]
final class access_test extends \advanced_testcase {
    /**
     * Only editingteacher and manager archetypes get the capability by default.
     */
    public function test_default_archetypes(): void {
        $this->assertSame(CAP_ALLOW, get_default_capabilities('editingteacher')['local/askdata:ask'] ?? null);
        $this->assertSame(CAP_ALLOW, get_default_capabilities('manager')['local/askdata:ask'] ?? null);
        $this->assertArrayNotHasKey('local/askdata:ask', get_default_capabilities('student'));
        $this->assertArrayNotHasKey('local/askdata:ask', get_default_capabilities('teacher'));
        $this->assertArrayNotHasKey('local/askdata:ask', get_default_capabilities('user'));
    }

    /**
     * Teachers hold the capability in their course; students do not.
     */
    public function test_has_capability_by_role(): void {
        $this->resetAfterTest();
        $gen = $this->getDataGenerator();
        $course = $gen->create_course();
        $context = \context_course::instance($course->id);
        $teacher = $gen->create_and_enrol($course, 'editingteacher');
        $student = $gen->create_and_enrol($course, 'student');

        $this->assertTrue(has_capability('local/askdata:ask', $context, $teacher));
        $this->assertFalse(has_capability('local/askdata:ask', $context, $student));
    }

    /**
     * The navigation node is added for teachers and not for students.
     */
    public function test_navigation_node(): void {
        global $CFG;
        require_once($CFG->dirroot . '/local/askdata/lib.php');
        $this->resetAfterTest();
        $gen = $this->getDataGenerator();
        $course = $gen->create_course();
        $context = \context_course::instance($course->id);
        $teacher = $gen->create_and_enrol($course, 'editingteacher');
        $student = $gen->create_and_enrol($course, 'student');

        $this->setUser($teacher);
        $node = \navigation_node::create('course');
        local_askdata_extend_navigation_course($node, $course, $context);
        $this->assertNotFalse($node->get('local_askdata'));

        $this->setUser($student);
        $node = \navigation_node::create('course');
        local_askdata_extend_navigation_course($node, $course, $context);
        $this->assertFalse($node->get('local_askdata'));
    }
}
