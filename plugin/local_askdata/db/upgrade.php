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
 * Upgrade steps for local_askdata.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

/**
 * Runs the upgrade steps.
 *
 * @param int $oldversion Version installed before this upgrade.
 * @return bool
 */
function xmldb_local_askdata_upgrade($oldversion) {
    if ($oldversion < 2026100401) {
        // The old 60 s default gave up before the service; move sites still on it to the new default.
        if ((int) get_config('local_askdata', 'timeout') === 60) {
            set_config('timeout', \local_askdata\local\client::DEFAULT_TIMEOUT, 'local_askdata');
        }
        upgrade_plugin_savepoint(true, 2026100401, 'local', 'askdata');
    }
    return true;
}
