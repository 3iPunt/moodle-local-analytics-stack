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
 * HMAC helpers shared with the analytics service.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class signer {
    /**
     * Signs a request body.
     *
     * The signed message is the timestamp, a newline, and the raw body.
     *
     * @param string $secret The shared secret.
     * @param int $timestamp Unix timestamp in seconds, sent in the X-Askdata-Timestamp header.
     * @param string $body The raw JSON body exactly as sent.
     * @return string Lowercase hex HMAC-SHA256.
     */
    public static function sign(string $secret, int $timestamp, string $body): string {
        return hash_hmac('sha256', $timestamp . "\n" . $body, $secret);
    }

    /**
     * Returns the pseudonymous reference for a user.
     *
     * @param string $secret The shared secret.
     * @param int $userid The Moodle user id.
     * @return string Lowercase hex HMAC-SHA256 of the user id.
     */
    public static function user_ref(string $secret, int $userid): string {
        return hash_hmac('sha256', (string) $userid, $secret);
    }
}
