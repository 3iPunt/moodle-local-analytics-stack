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
 * Error raised when the analytics service cannot answer a question.
 *
 * The message is always safe to show to the user. It never contains the
 * shared secret, the request signature or a raw stack trace.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class service_exception extends \moodle_exception {
    /** @var string Machine-readable reason, used for logging. */
    public readonly string $reason;

    /** @var int HTTP status code, or 0 when no response was received. */
    public readonly int $status;

    /**
     * Constructor.
     *
     * @param string $errorcode Language string key in local_askdata.
     * @param string $reason Machine-readable reason.
     * @param int $status HTTP status code, or 0.
     * @param mixed $a Extra data for the language string.
     * @param string|null $debuginfo Developer details, never shown to normal users.
     */
    public function __construct(string $errorcode, string $reason, int $status = 0, $a = null, ?string $debuginfo = null) {
        $this->reason = $reason;
        $this->status = $status;
        parent::__construct($errorcode, 'local_askdata', '', $a, $debuginfo);
    }
}
