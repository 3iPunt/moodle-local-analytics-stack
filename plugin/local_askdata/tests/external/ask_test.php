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
use local_askdata\event\question_asked;
use local_askdata\local\client;
use local_askdata\local\service_exception;
use local_askdata\local\signer;

/**
 * Tests for the local_askdata_ask external function.
 *
 * The HTTP call is replaced with a canned response, so these tests never hit the network.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
#[\PHPUnit\Framework\Attributes\CoversClass(ask::class)]
#[\PHPUnit\Framework\Attributes\CoversClass(client::class)]
#[\PHPUnit\Framework\Attributes\CoversClass(question_asked::class)]
final class ask_test extends \advanced_testcase {
    /** @var string Shared secret used by the tests. */
    private const SECRET = 'test-secret';

    #[\Override]
    protected function setUp(): void {
        parent::setUp();
        $this->resetAfterTest();
        set_config('serviceurl', 'http://analytics.invalid:8000/', 'local_askdata');
        set_config('sharedsecret', self::SECRET, 'local_askdata');
        set_config('timeout', 10, 'local_askdata');
        set_config('maxrows', 200, 'local_askdata');
    }

    #[\Override]
    protected function tearDown(): void {
        client::set_test_response(null);
        parent::tearDown();
    }

    /**
     * Creates three courses and a teacher in the first two.
     *
     * @return array [teacher, course1, course2, course3]
     */
    private function setup_courses(): array {
        $gen = $this->getDataGenerator();
        $c1 = $gen->create_course();
        $c2 = $gen->create_course();
        $c3 = $gen->create_course();
        $teacher = $gen->create_and_enrol($c1, 'editingteacher');
        $gen->enrol_user($teacher->id, $c2->id, 'editingteacher');
        return [$teacher, $c1, $c2, $c3];
    }

    /**
     * A student without the capability is rejected before any HTTP call.
     */
    public function test_student_is_rejected(): void {
        $course = $this->getDataGenerator()->create_course();
        $student = $this->getDataGenerator()->create_and_enrol($course, 'student');
        $this->setUser($student);
        client::set_test_response(200, '{"sql":"","columns":[],"rows":[]}');

        try {
            ask::execute((int) $course->id, 'Which students are inactive?');
            $this->fail('Expected required_capability_exception');
        } catch (\required_capability_exception $e) {
            $this->assertSame('nopermissions', $e->errorcode);
        }
        $this->assertNull(client::get_last_test_request());
    }

    /**
     * A teacher gets the answer, the request is signed and scoped, and an event is logged.
     */
    public function test_teacher_gets_answer(): void {
        [$teacher, $c1, $c2] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(200, json_encode([
            'sql' => 'SELECT 1 AS n',
            'columns' => ['course', 'students', 'avg'],
            'rows' => [['DA101', 95, null], ['PROG101', 85, 66.6]],
            'elapsed_ms' => 1234,
        ]));
        $sink = $this->redirectEvents();

        $result = ask::execute((int) $c1->id, 'Which courses do I teach?');
        $result = external_api::clean_returnvalue(ask::execute_returns(), $result);

        $this->assertSame('SELECT 1 AS n', $result['sql']);
        $this->assertSame(['course', 'students', 'avg'], $result['columns']);
        $this->assertSame([['DA101', '95', ''], ['PROG101', '85', '66.6']], $result['rows']);
        $this->assertSame(1234, $result['elapsed_ms']);
        $this->assertFalse($result['truncated']);

        $request = client::get_last_test_request();
        $this->assertSame('http://analytics.invalid:8000/ask', $request['url']);
        $body = json_decode($request['body'], true);
        $expectedids = [(int) $c1->id, (int) $c2->id];
        sort($expectedids);
        $this->assertSame('Which courses do I teach?', $body['question']);
        $this->assertSame($expectedids, $body['course_ids']);
        $this->assertSame(signer::user_ref(self::SECRET, (int) $teacher->id), $body['user_ref']);
        $this->assertSame(200, $body['max_rows']);
        $this->assertStringNotContainsString($teacher->email, $request['body']);
        $this->assertStringNotContainsString($teacher->username, $request['body']);

        $headers = [];
        foreach ($request['headers'] as $line) {
            [$name, $value] = array_map('trim', explode(':', $line, 2));
            $headers[$name] = $value;
        }
        $this->assertSame('application/json', $headers['Content-Type']);
        $timestamp = (int) $headers['X-Askdata-Timestamp'];
        $this->assertEqualsWithDelta(time(), $timestamp, 5);
        $this->assertSame(signer::sign(self::SECRET, $timestamp, $request['body']), $headers['X-Askdata-Signature']);
        $this->assertStringNotContainsString(self::SECRET, implode("\n", $request['headers']) . $request['body']);

        $events = array_values(array_filter($sink->get_events(), fn($e) => $e instanceof question_asked));
        $this->assertCount(1, $events);
        $event = $events[0];
        $this->assertSame((int) $c1->id, (int) $event->courseid);
        $this->assertSame('Which courses do I teach?', $event->other['question']);
        $this->assertSame($expectedids, $event->other['courseids']);
        $this->assertTrue($event->other['ok']);
        $this->assertSame(1234, $event->other['elapsed_ms']);
        $this->assertEquals(new \moodle_url('/local/askdata/index.php', ['courseid' => $c1->id]), $event->get_url());
    }

    /**
     * Rows beyond the configured maximum are cut and flagged.
     */
    public function test_rows_are_truncated(): void {
        set_config('maxrows', 2, 'local_askdata');
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(200, json_encode([
            'sql' => 'SELECT n',
            'columns' => ['n'],
            'rows' => [[1], [2], [3]],
            'elapsed_ms' => 5,
        ]));

        $result = ask::execute((int) $c1->id, 'Count to three');
        $this->assertSame([['1'], ['2']], $result['rows']);
        $this->assertTrue($result['truncated']);
        $this->assertSame(2, json_decode(client::get_last_test_request()['body'], true)['max_rows']);
    }

    /**
     * Service errors are surfaced with the friendly message and logged as failed.
     */
    public function test_service_error_message(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(422, json_encode([
            'detail' => ['reason' => 'guard_rejected', 'message' => 'The query touches a table that is not allowed.'],
        ]));
        $sink = $this->redirectEvents();

        try {
            ask::execute((int) $c1->id, 'Drop everything');
            $this->fail('Expected service_exception');
        } catch (service_exception $e) {
            $this->assertSame('error_service', $e->errorcode);
            $this->assertSame('guard_rejected', $e->reason);
            $this->assertStringContainsString('The query touches a table that is not allowed.', $e->getMessage());
        }
        $events = array_values(array_filter($sink->get_events(), fn($e) => $e instanceof question_asked));
        $this->assertCount(1, $events);
        $this->assertFalse($events[0]->other['ok']);
    }

    /**
     * Error details given as a plain string are also surfaced.
     */
    public function test_service_error_string_detail(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(400, json_encode(['detail' => 'Question is too vague.']));

        $this->expectException(service_exception::class);
        $this->expectExceptionMessage('Question is too vague.');
        ask::execute((int) $c1->id, 'Hm?');
    }

    /**
     * Server errors do not leak their details.
     */
    public function test_server_error_is_generic(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(500, json_encode(['detail' => 'Traceback (most recent call last): secret stuff']));

        try {
            ask::execute((int) $c1->id, 'Anything');
            $this->fail('Expected service_exception');
        } catch (service_exception $e) {
            $this->assertSame('error_service_generic', $e->errorcode);
            $this->assertStringNotContainsString('Traceback', $e->getMessage());
        }
    }

    /**
     * A 502 with reason model_unavailable gets its own message.
     */
    public function test_model_unavailable_has_dedicated_message(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(502, json_encode(['detail' => ['reason' => 'model_unavailable', 'message' => 'runner died: /internal/path']]));

        try {
            ask::execute((int) $c1->id, 'Anything');
            $this->fail('Expected service_exception');
        } catch (service_exception $e) {
            $this->assertSame('error_model_unavailable', $e->errorcode);
            $this->assertSame('model_unavailable', $e->reason);
            $this->assertSame(502, $e->status);
            $this->assertStringContainsString('Ollama', $e->getMessage());
            $this->assertStringNotContainsString('/internal/path', $e->getMessage());
        }
    }

    /**
     * Any other 502 stays generic.
     */
    public function test_other_bad_gateway_is_generic(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(502, json_encode(['detail' => ['reason' => 'upstream', 'message' => 'x']]));

        try {
            ask::execute((int) $c1->id, 'Anything');
            $this->fail('Expected service_exception');
        } catch (service_exception $e) {
            $this->assertSame('error_service_generic', $e->errorcode);
        }
    }

    /**
     * A 504 maps to the timeout message.
     */
    public function test_gateway_timeout_maps_to_timeout_message(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(504, json_encode(['detail' => ['reason' => 'timeout', 'message' => 'model took too long']]));

        try {
            ask::execute((int) $c1->id, 'Anything');
            $this->fail('Expected service_exception');
        } catch (service_exception $e) {
            $this->assertSame('error_timeout', $e->errorcode);
            $this->assertSame(504, $e->status);
        }
    }

    /**
     * A curl timeout maps to the timeout message, not to "unreachable".
     */
    public function test_curl_timeout_maps_to_timeout_message(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(0, '', 28);

        try {
            ask::execute((int) $c1->id, 'Anything');
            $this->fail('Expected service_exception');
        } catch (service_exception $e) {
            $this->assertSame('error_timeout', $e->errorcode);
            $this->assertSame('timeout', $e->reason);
        }
    }

    /**
     * A 503 busy maps to the busy message.
     */
    public function test_busy_maps_to_busy_message(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(503, json_encode(['detail' => ['reason' => 'busy', 'message' => 'try again shortly']]));

        try {
            ask::execute((int) $c1->id, 'Anything');
            $this->fail('Expected service_exception');
        } catch (service_exception $e) {
            $this->assertSame('error_busy', $e->errorcode);
            $this->assertSame('busy', $e->reason);
            $this->assertSame(503, $e->status);
        }
    }

    /**
     * Any other 503 stays generic.
     */
    public function test_other_service_unavailable_is_generic(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(503, json_encode(['status' => 'starting', 'db_file' => false]));

        try {
            ask::execute((int) $c1->id, 'Anything');
            $this->fail('Expected service_exception');
        } catch (service_exception $e) {
            $this->assertSame('error_service_generic', $e->errorcode);
        }
    }

    /**
     * The external function releases the session lock while it waits for the service.
     */
    public function test_function_uses_a_readonly_session(): void {
        $info = external_api::external_function_info('local_askdata_ask');
        $this->assertTrue($info->readonlysession);
    }

    /**
     * A rejected signature maps to the signature error.
     */
    public function test_signature_error(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(401, json_encode(['detail' => ['reason' => 'bad_signature', 'message' => 'Bad signature']]));

        try {
            ask::execute((int) $c1->id, 'Anything');
            $this->fail('Expected service_exception');
        } catch (service_exception $e) {
            $this->assertSame('error_signature', $e->errorcode);
            $this->assertSame('bad_signature', $e->reason);
        }
    }

    /**
     * Transport failures map to the unreachable error.
     */
    public function test_unreachable(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(0, '', 7);

        try {
            ask::execute((int) $c1->id, 'Anything');
            $this->fail('Expected service_exception');
        } catch (service_exception $e) {
            $this->assertSame('error_unreachable', $e->errorcode);
        }
    }

    /**
     * Missing configuration is reported without calling the service.
     */
    public function test_not_configured(): void {
        set_config('sharedsecret', '', 'local_askdata');
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(200, '{}');

        try {
            ask::execute((int) $c1->id, 'Anything');
            $this->fail('Expected service_exception');
        } catch (service_exception $e) {
            $this->assertSame('error_notconfigured', $e->errorcode);
        }
        $this->assertNull(client::get_last_test_request());
    }

    /**
     * A malformed success response is rejected.
     */
    public function test_bad_response(): void {
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        client::set_test_response(200, 'not json');

        $this->expectException(service_exception::class);
        ask::execute((int) $c1->id, 'Anything');
    }

    /**
     * Failures outside the service call are audited as well.
     */
    public function test_every_failure_is_logged(): void {
        set_config('sharedsecret', '', 'local_askdata');
        [$teacher, $c1] = $this->setup_courses();
        $this->setUser($teacher);
        $sink = $this->redirectEvents();

        foreach (['Anything', '   '] as $question) {
            try {
                ask::execute((int) $c1->id, $question);
                $this->fail('Expected an exception');
            } catch (\moodle_exception $e) {
                $this->assertContains($e->errorcode, ['error_notconfigured', 'invalidparameter']);
            }
        }

        $events = array_values(array_filter($sink->get_events(), fn($e) => $e instanceof question_asked));
        $this->assertCount(2, $events);
        foreach ($events as $event) {
            $this->assertFalse($event->other['ok']);
            $this->assertIsInt($event->other['elapsed_ms']);
            $this->assertSame((int) $c1->id, (int) $event->courseid);
        }
        $this->assertSame('Anything', $events[0]->other['question']);
    }

    /**
     * The event refuses badly typed data.
     */
    public function test_event_validates_types(): void {
        $course = $this->getDataGenerator()->create_course();
        $context = \context_course::instance($course->id);
        $valid = ['question' => 'Q', 'courseids' => [(int) $course->id], 'elapsed_ms' => 5, 'ok' => true];
        $this->assertInstanceOf(question_asked::class, question_asked::create(['context' => $context, 'other' => $valid]));

        foreach (['ok' => 1, 'elapsed_ms' => '5', 'courseids' => '2', 'question' => null] as $key => $bad) {
            try {
                question_asked::create(['context' => $context, 'other' => array_merge($valid, [$key => $bad])]);
                $this->fail("Expected coding_exception for {$key}");
            } catch (\coding_exception $e) {
                $this->assertStringContainsString($key, $e->getMessage());
            }
        }
    }
}
