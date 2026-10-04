"""A tiny in-memory Moodle catalog "m" for unit tests of views.sql.

Edge cases: user 13 is deleted but still has enrolments, log events, completions,
grades and a submission; user 14's enrolment ended yesterday; user 15's starts in
5 days; user 11's ends in 30 days (still active); user 12 is both editingteacher
and teacher in course 2; course modules 1004 (page) and 1005 (assign, with a
grade item, grade, completion and submission) are being deleted.
"""

from __future__ import annotations

NOW = 1_790_000_000
DAY = 86_400

DDL = """
CREATE TABLE m.mdl_course (id BIGINT, shortname VARCHAR, fullname VARCHAR, startdate BIGINT,
    visible BOOLEAN, enablecompletion BOOLEAN, "format" VARCHAR, summary VARCHAR);
CREATE TABLE m.mdl_user (id BIGINT, username VARCHAR, firstname VARCHAR, lastname VARCHAR, email VARCHAR,
    lastip VARCHAR, deleted BOOLEAN, lastaccess BIGINT);
CREATE TABLE m.mdl_enrol (id BIGINT, courseid BIGINT, status BIGINT);
CREATE TABLE m.mdl_user_enrolments (id BIGINT, enrolid BIGINT, userid BIGINT, status BIGINT,
    timestart BIGINT, timeend BIGINT, timecreated BIGINT);
CREATE TABLE m.mdl_context (id BIGINT, contextlevel BIGINT, instanceid BIGINT);
CREATE TABLE m.mdl_role (id BIGINT, shortname VARCHAR);
CREATE TABLE m.mdl_role_assignments (id BIGINT, roleid BIGINT, contextid BIGINT, userid BIGINT);
CREATE TABLE m.mdl_user_lastaccess (id BIGINT, userid BIGINT, courseid BIGINT, timeaccess BIGINT);
CREATE TABLE m.mdl_logstore_standard_log (id BIGINT, courseid BIGINT, userid BIGINT, timecreated BIGINT,
    origin VARCHAR, action VARCHAR, crud VARCHAR, contextlevel BIGINT, contextinstanceid BIGINT,
    anonymous BOOLEAN, ip VARCHAR);
CREATE TABLE m.mdl_modules (id BIGINT, name VARCHAR);
CREATE TABLE m.mdl_course_modules (id BIGINT, course BIGINT, module BIGINT, instance BIGINT, section BIGINT,
    visible BOOLEAN, completion TINYINT, deletioninprogress BOOLEAN);
CREATE TABLE m.mdl_course_sections (id BIGINT, course BIGINT, section BIGINT);
CREATE TABLE m.mdl_assign (id BIGINT, course BIGINT, name VARCHAR, duedate BIGINT);
CREATE TABLE m.mdl_quiz (id BIGINT, course BIGINT, name VARCHAR, timeclose BIGINT);
CREATE TABLE m.mdl_page (id BIGINT, course BIGINT, name VARCHAR);
CREATE TABLE m.mdl_forum (id BIGINT, course BIGINT, name VARCHAR);
CREATE TABLE m.mdl_url (id BIGINT, course BIGINT, name VARCHAR);
CREATE TABLE m.mdl_resource (id BIGINT, course BIGINT, name VARCHAR);
CREATE TABLE m.mdl_book (id BIGINT, course BIGINT, name VARCHAR);
CREATE TABLE m.mdl_label (id BIGINT, course BIGINT, name VARCHAR);
CREATE TABLE m.mdl_course_modules_completion (id BIGINT, coursemoduleid BIGINT, userid BIGINT,
    completionstate TINYINT, timemodified BIGINT);
CREATE TABLE m.mdl_course_completions (id BIGINT, userid BIGINT, course BIGINT, timecompleted BIGINT);
CREATE TABLE m.mdl_grade_items (id BIGINT, courseid BIGINT, itemname VARCHAR, itemtype VARCHAR,
    itemmodule VARCHAR, iteminstance BIGINT, grademax DECIMAL(10,5), grademin DECIMAL(10,5));
CREATE TABLE m.mdl_grade_grades (id BIGINT, itemid BIGINT, userid BIGINT, finalgrade DECIMAL(10,5),
    rawgrade DECIMAL(10,5), timemodified BIGINT);
CREATE TABLE m.mdl_assign_submission (id BIGINT, assignment BIGINT, userid BIGINT, status VARCHAR,
    timemodified BIGINT, latest TINYINT);
"""

DATA = f"""
INSERT INTO m.mdl_course VALUES
    (1, 'site', 'Site', 0, true, false, 'site', ''),
    (2, 'C1', 'Course One', {NOW - 60 * DAY}, true, true, 'topics', 'secret summary'),
    (3, 'C2', 'Course Two', 0, false, false, 'topics', '');
INSERT INTO m.mdl_user VALUES
    (10, 'alice', 'Alice', 'Doe', 'alice@example.com', '10.0.0.1', false, {NOW - DAY}),
    (11, 'bob', 'Bob', 'Roe', 'bob@example.com', '10.0.0.2', false, 0),
    (12, 'tess', 'Tess', 'Teach', 'tess@example.com', '10.0.0.3', false, {NOW - 2 * DAY}),
    (13, 'gone', 'Gone', 'User', 'gone@example.com', '10.0.0.4', true, {NOW}),
    (14, 'expired', 'Ex', 'Pired', 'ex@example.com', '10.0.0.5', false, {NOW - 3 * DAY}),
    (15, 'future', 'Fu', 'Ture', 'fu@example.com', '10.0.0.6', false, 0);
INSERT INTO m.mdl_enrol VALUES (100, 2, 0), (101, 3, 0);
INSERT INTO m.mdl_user_enrolments VALUES
    (1, 100, 10, 0, {NOW - 30 * DAY}, 0, {NOW - 31 * DAY}),
    (2, 100, 11, 0, 0, {NOW + 30 * DAY}, {NOW - 29 * DAY}),
    (3, 100, 12, 0, {NOW - 40 * DAY}, 0, 0),
    (4, 100, 13, 0, {NOW - 40 * DAY}, 0, 0),
    (5, 101, 10, 1, {NOW - 10 * DAY}, 0, 0),
    (6, 100, 14, 0, {NOW - 50 * DAY}, {NOW - DAY}, 0),
    (7, 100, 15, 0, {NOW + 5 * DAY}, 0, {NOW - DAY});
INSERT INTO m.mdl_context VALUES (500, 50, 2), (501, 50, 3), (502, 70, 1000);
INSERT INTO m.mdl_role VALUES (3, 'editingteacher'), (4, 'teacher'), (5, 'student');
INSERT INTO m.mdl_role_assignments VALUES
    (1, 5, 500, 10), (2, 5, 500, 11), (3, 3, 500, 12), (4, 5, 500, 13), (5, 5, 501, 10), (6, 3, 502, 12),
    (7, 4, 500, 12), (8, 5, 500, 14), (9, 5, 500, 15);
INSERT INTO m.mdl_user_lastaccess VALUES (1, 10, 2, {NOW - 20 * DAY - 3600});
INSERT INTO m.mdl_logstore_standard_log VALUES
    (1, 2, 10, {NOW - 20 * DAY - 3600}, 'web', 'viewed', 'r', 50, 2, false, '10.0.0.1'),
    (2, 2, 10, {NOW - 20 * DAY - 3000}, 'web', 'viewed', 'r', 70, 1000, false, '10.0.0.1'),
    (3, 2, 10, {NOW - 20 * DAY - 2000}, 'web', 'submitted', 'c', 70, 1001, false, '10.0.0.1'),
    (4, 2, 10, {NOW - 20 * DAY - 1000}, 'cli', 'viewed', 'r', 70, 1000, false, ''),
    (5, 1, 10, {NOW - DAY}, 'web', 'viewed', 'r', 50, 1, false, '10.0.0.1'),
    (6, 2, 0, {NOW - DAY}, 'web', 'viewed', 'r', 50, 2, false, ''),
    (7, 2, 12, {NOW - 2 * DAY}, 'web', 'graded', 'u', 70, 1001, false, '10.0.0.3'),
    (8, 2, 13, {NOW - 3 * DAY}, 'web', 'viewed', 'r', 50, 2, false, '10.0.0.4');
INSERT INTO m.mdl_modules VALUES (1, 'page'), (2, 'assign'), (3, 'quiz'), (4, 'lti');
INSERT INTO m.mdl_course_sections VALUES (900, 2, 0), (901, 2, 1), (902, 2, 2);
INSERT INTO m.mdl_course_modules VALUES
    (1000, 2, 1, 1, 901, true, 1, false),
    (1001, 2, 2, 1, 902, true, 2, false),
    (1002, 2, 3, 1, 902, false, 0, false),
    (1003, 2, 4, 1, 900, true, 0, false),
    (1004, 2, 1, 2, 900, true, 1, true),
    (1005, 2, 2, 2, 902, true, 1, true);
INSERT INTO m.mdl_page VALUES (1, 2, 'Welcome'), (2, 2, 'Being deleted');
INSERT INTO m.mdl_assign VALUES (1, 2, 'Final Project', {NOW + 3 * DAY}), (2, 2, 'Being deleted', 0);
INSERT INTO m.mdl_quiz VALUES (1, 2, 'Checkpoint quiz', 0);
INSERT INTO m.mdl_course_modules_completion VALUES
    (1, 1000, 10, 1, {NOW - 20 * DAY}), (2, 1001, 10, 2, {NOW - 19 * DAY}), (3, 1000, 11, 0, {NOW - 5 * DAY}),
    (4, 1004, 10, 1, {NOW - 4 * DAY}), (5, 1000, 13, 1, {NOW - 4 * DAY});
INSERT INTO m.mdl_course_completions VALUES (1, 10, 2, {NOW - 18 * DAY}), (2, 11, 2, 0), (3, 13, 2, {NOW - 4 * DAY});
INSERT INTO m.mdl_grade_items VALUES
    (50, 2, NULL, 'course', NULL, 2, 100, 0),
    (51, 2, 'Final Project', 'mod', 'assign', 1, 100, 0),
    (52, 2, 'Checkpoint quiz', 'mod', 'quiz', 1, 10, 0),
    (53, 1, 'Site item', 'manual', NULL, NULL, 10, 0),
    (54, 2, 'Being deleted', 'mod', 'assign', 2, 100, 0);
INSERT INTO m.mdl_grade_grades VALUES
    (1, 51, 10, 72.5, 70, {NOW - 19 * DAY}), (2, 51, 11, NULL, NULL, 0), (3, 52, 10, 8, 8, {NOW - 19 * DAY}),
    (4, 54, 10, 50, 50, {NOW - 4 * DAY}), (5, 51, 13, 60, 60, {NOW - 4 * DAY});
INSERT INTO m.mdl_assign_submission VALUES
    (1, 1, 10, 'submitted', {NOW - 19 * DAY}, 1), (2, 1, 11, 'new', {NOW - 5 * DAY}, 1), (3, 1, 0, 'submitted', 1, 1),
    (4, 2, 10, 'submitted', {NOW - 4 * DAY}, 1), (5, 1, 13, 'submitted', {NOW - 4 * DAY}, 1);
"""


def attach_fake_moodle(con) -> None:
    con.execute("ATTACH ':memory:' AS m")
    con.execute(DDL)
    con.execute(DATA)
