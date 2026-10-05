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
 * Tests for the HMAC signer.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
#[\PHPUnit\Framework\Attributes\CoversClass(signer::class)]
final class signer_test extends \basic_testcase {
    /**
     * The signature matches a vector computed with the analytics service's app.ask.sign.
     */
    public function test_sign_known_vector(): void {
        $body = '{"question":"How many students?","course_ids":[2,3]}';
        $this->assertSame(
            'da24559b2768e9929f3f8c0bbdb1adf216333c9fd83e9a1432f5a88222133571',
            signer::sign('test-secret', 'POST', '/ask', 1700000000, $body)
        );
    }

    /**
     * The signature changes when any signed part changes.
     */
    public function test_sign_depends_on_all_inputs(): void {
        $base = signer::sign('s', 'POST', '/ask', 1700000000, '{}');
        $this->assertNotSame($base, signer::sign('t', 'POST', '/ask', 1700000000, '{}'));
        $this->assertNotSame($base, signer::sign('s', 'GET', '/ask', 1700000000, '{}'));
        $this->assertNotSame($base, signer::sign('s', 'POST', '/health', 1700000000, '{}'));
        $this->assertNotSame($base, signer::sign('s', 'POST', '/ask', 1700000001, '{}'));
        $this->assertNotSame($base, signer::sign('s', 'POST', '/ask', 1700000000, '{ }'));
    }

    /**
     * The method is upper-cased before signing.
     */
    public function test_sign_uppercases_the_method(): void {
        $this->assertSame(signer::sign('s', 'POST', '/ask', 1, '{}'), signer::sign('s', 'post', '/ask', 1, '{}'));
    }

    /**
     * The user reference matches a known vector and does not contain the user id in clear.
     */
    public function test_user_ref_known_vector(): void {
        $ref = signer::user_ref('test-secret', 42);
        $this->assertSame('0c448d9ba9697edc6e65d581ad07fba78e907baad3c1e452d3ead109363f97bf', $ref);
        $this->assertMatchesRegularExpression('/^[0-9a-f]{64}$/', $ref);
        $this->assertNotSame($ref, signer::user_ref('other-secret', 42));
    }

    /**
     * The primitive is standard HMAC-SHA256 (RFC 2104 example vector).
     */
    public function test_hmac_reference_vector(): void {
        $this->assertSame(
            'f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8',
            hash_hmac('sha256', 'The quick brown fox jumps over the lazy dog', 'key')
        );
    }
}
