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

namespace local_askdata\privacy;

use core_privacy\local\metadata\collection;
use core_privacy\local\request\approved_contextlist;
use core_privacy\local\request\approved_userlist;
use core_privacy\local\request\contextlist;
use core_privacy\local\request\userlist;

/**
 * Privacy provider for local_askdata.
 *
 * The plugin stores no personal data in its own tables. It sends questions to
 * the analytics service together with a pseudonymous user reference, which is
 * declared here as an external location. Questions are also recorded in the
 * standard log through the question_asked event, which the log stores export.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class provider implements
    \core_privacy\local\metadata\provider,
    \core_privacy\local\request\core_userlist_provider,
    \core_privacy\local\request\plugin\provider {
    /**
     * Describes the data sent to the analytics service.
     *
     * @param collection $collection The collection to add metadata to.
     * @return collection
     */
    public static function get_metadata(collection $collection): collection {
        $collection->add_external_location_link('analytics_service', [
            'question' => 'privacy:metadata:analytics_service:question',
            'course_ids' => 'privacy:metadata:analytics_service:course_ids',
            'user_ref' => 'privacy:metadata:analytics_service:user_ref',
        ], 'privacy:metadata:analytics_service');
        return $collection;
    }

    /**
     * No user data is stored by this plugin.
     *
     * @param int $userid The user id.
     * @return contextlist
     */
    public static function get_contexts_for_userid(int $userid): contextlist {
        return new contextlist();
    }

    /**
     * No user data is stored by this plugin.
     *
     * @param userlist $userlist The userlist.
     */
    public static function get_users_in_context(userlist $userlist) {
    }

    /**
     * No user data is stored by this plugin.
     *
     * @param approved_contextlist $contextlist The approved contexts.
     */
    public static function export_user_data(approved_contextlist $contextlist) {
    }

    /**
     * No user data is stored by this plugin.
     *
     * @param \context $context The context.
     */
    public static function delete_data_for_all_users_in_context(\context $context) {
    }

    /**
     * No user data is stored by this plugin.
     *
     * @param approved_contextlist $contextlist The approved contexts.
     */
    public static function delete_data_for_user(approved_contextlist $contextlist) {
    }

    /**
     * No user data is stored by this plugin.
     *
     * @param approved_userlist $userlist The approved users.
     */
    public static function delete_data_for_users(approved_userlist $userlist) {
    }
}
