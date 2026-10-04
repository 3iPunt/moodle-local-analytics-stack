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
 * Admin settings for local_askdata.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

if ($hassiteconfig) {
    $settings = new admin_settingpage('local_askdata', new lang_string('pluginname', 'local_askdata'));

    $settings->add(new admin_setting_configtext(
        'local_askdata/serviceurl',
        new lang_string('serviceurl', 'local_askdata'),
        new lang_string('serviceurl_desc', 'local_askdata'),
        'http://analytics:8000',
        PARAM_URL
    ));

    $settings->add(new admin_setting_configpasswordunmask(
        'local_askdata/sharedsecret',
        new lang_string('sharedsecret', 'local_askdata'),
        new lang_string('sharedsecret_desc', 'local_askdata'),
        ''
    ));

    $settings->add(new admin_setting_configtext(
        'local_askdata/timeout',
        new lang_string('timeout', 'local_askdata'),
        new lang_string('timeout_desc', 'local_askdata'),
        \local_askdata\local\client::DEFAULT_TIMEOUT,
        PARAM_INT
    ));

    $settings->add(new admin_setting_configtext(
        'local_askdata/maxrows',
        new lang_string('maxrows', 'local_askdata'),
        new lang_string('maxrows_desc', 'local_askdata'),
        200,
        PARAM_INT
    ));

    $ADMIN->add('localplugins', $settings);
}
