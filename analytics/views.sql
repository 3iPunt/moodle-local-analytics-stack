-- Moodle -> DuckDB export: the single source of the analytics data model.
--
-- Reads Moodle tables through the catalog alias "m". The exporter provides "m"
-- either as the live MySQL database (DuckDB mysql_scanner, READ_ONLY) or as
-- views over Parquet staging files dumped with pymysql. Every output column is
-- cast explicitly so both sources produce identical types.
--
-- Placeholders substituted by app/export.py as SQL literals: {salt}, {now_epoch}.
-- The salt only lives in TEMP macros, which are never written to the file.
-- All timestamps are UTC. Moodle stores them as epoch seconds; 0 means "never".

CREATE OR REPLACE TEMP MACRO epoch_ts(x) AS
    CASE WHEN CAST(x AS BIGINT) > 0 THEN make_timestamp(CAST(x AS BIGINT) * 1000000) END;

CREATE OR REPLACE TEMP MACRO flag(x) AS CAST(x AS INTEGER) <> 0;

CREATE OR REPLACE TEMP MACRO pseudo(id) AS md5(CAST(CAST(id AS BIGINT) AS VARCHAR) || {salt});

CREATE OR REPLACE TEMP MACRO export_epoch() AS CAST({now_epoch} AS BIGINT);

CREATE SCHEMA IF NOT EXISTS base;

-- course ---------------------------------------------------------------------

CREATE OR REPLACE TABLE base.course AS
SELECT
    CAST(c.id AS BIGINT) AS course_id,
    CAST(c.shortname AS VARCHAR) AS shortname,
    CAST(c.fullname AS VARCHAR) AS fullname,
    CAST(epoch_ts(c.startdate) AS DATE) AS start_date,
    flag(c.visible) AS visible,
    flag(c.enablecompletion) AS completion_enabled
FROM m.mdl_course AS c
WHERE c."format" <> 'site';

COMMENT ON TABLE base.course IS 'One row per Moodle course (the site front page is excluded). Join every other table to it with course_id to get the course shortname or fullname.';
COMMENT ON COLUMN base.course.course_id IS 'Moodle course id. Primary key. Every other table has course_id.';
COMMENT ON COLUMN base.course.shortname IS 'Short course code shown to users, for example DA101. Unique.';
COMMENT ON COLUMN base.course.fullname IS 'Full course title, for example Data Analysis 101.';
COMMENT ON COLUMN base.course.start_date IS 'Course start date (UTC). NULL when not set.';
COMMENT ON COLUMN base.course.visible IS 'TRUE when the course is visible to students.';
COMMENT ON COLUMN base.course.completion_enabled IS 'TRUE when completion tracking is enabled in the course, so completion and course_completion rows are meaningful.';

-- participant ----------------------------------------------------------------

CREATE OR REPLACE TABLE base.participant AS
WITH enrolment AS (
    SELECT
        e.courseid AS course_id,
        ue.userid,
        min(CASE WHEN CAST(ue.timestart AS BIGINT) > 0 THEN ue.timestart ELSE ue.timecreated END) AS enrolled_epoch,
        bool_and(flag(ue.status) OR flag(e.status)) AS suspended
    FROM m.mdl_user_enrolments AS ue
    JOIN m.mdl_enrol AS e ON e.id = ue.enrolid
    GROUP BY e.courseid, ue.userid
),
course_role AS (
    SELECT DISTINCT ctx.instanceid AS course_id, ra.userid, r.shortname AS role
    FROM m.mdl_role_assignments AS ra
    JOIN m.mdl_context AS ctx ON ctx.id = ra.contextid AND CAST(ctx.contextlevel AS INTEGER) = 50
    JOIN m.mdl_role AS r ON r.id = ra.roleid
),
access AS (
    SELECT
        en.course_id,
        en.userid,
        CASE
            WHEN CAST(la.timeaccess AS BIGINT) > 0 THEN CAST(la.timeaccess AS BIGINT)
            WHEN CAST(u.lastaccess AS BIGINT) > 0 THEN CAST(u.lastaccess AS BIGINT)
        END AS last_epoch
    FROM enrolment AS en
    JOIN m.mdl_user AS u ON u.id = en.userid
    LEFT JOIN m.mdl_user_lastaccess AS la ON la.userid = en.userid AND la.courseid = en.course_id
)
SELECT
    CAST(en.course_id AS BIGINT) AS course_id,
    pseudo(en.userid) AS user_ref,
    CAST(coalesce(cr.role, 'none') AS VARCHAR) AS role,
    CAST(epoch_ts(en.enrolled_epoch) AS DATE) AS enrolled_at,
    epoch_ts(a.last_epoch) AS last_access_at,
    CAST(floor((export_epoch() - a.last_epoch) / 86400) AS INTEGER) AS days_since_last_access,
    epoch_ts(u.lastaccess) AS last_login_at,
    CAST(floor((export_epoch() - CASE WHEN CAST(u.lastaccess AS BIGINT) > 0 THEN CAST(u.lastaccess AS BIGINT) END) / 86400) AS INTEGER) AS days_since_last_login,
    CAST(en.suspended AS BOOLEAN) AS suspended
FROM enrolment AS en
JOIN m.mdl_user AS u ON u.id = en.userid AND NOT flag(u.deleted)
JOIN access AS a ON a.course_id = en.course_id AND a.userid = en.userid
LEFT JOIN course_role AS cr ON cr.course_id = en.course_id AND cr.userid = en.userid
WHERE en.course_id IN (SELECT course_id FROM base.course);

COMMENT ON TABLE base.participant IS 'One row per (course_id, user_ref, role): users enrolled in a course with their course role. A student is a participant with role = ''student''; a teacher has role = ''editingteacher'' (or ''teacher'' for non-editing teachers). Count students with count(DISTINCT user_ref) WHERE role = ''student''. Join to other per-user tables on (course_id, user_ref).';
COMMENT ON COLUMN base.participant.course_id IS 'Course id. Join to course.course_id.';
COMMENT ON COLUMN base.participant.user_ref IS 'Pseudonymous user id (hex hash). Stable across tables and exports for the same user. Names and emails are not available.';
COMMENT ON COLUMN base.participant.role IS 'Course role shortname: ''student'', ''editingteacher'', ''teacher'', or another Moodle role. ''none'' when enrolled without a role.';
COMMENT ON COLUMN base.participant.enrolled_at IS 'Date the enrolment started (UTC).';
COMMENT ON COLUMN base.participant.last_access_at IS 'Last time the user accessed this course (UTC). Falls back to the last site access when Moodle has no course-level record. NULL when the user never accessed it.';
COMMENT ON COLUMN base.participant.days_since_last_access IS 'Whole days between last_access_at and the export time. NULL when the user never accessed the course. To find users who have not opened this course for N days use (days_since_last_access > N OR days_since_last_access IS NULL); for site logins use days_since_last_login.';
COMMENT ON COLUMN base.participant.last_login_at IS 'Last time the user was active anywhere on the Moodle site (UTC), in any course. NULL when the user never logged in.';
COMMENT ON COLUMN base.participant.days_since_last_login IS 'Whole days between last_login_at and the export time. Use it for questions about users who have not logged in: (days_since_last_login > N OR days_since_last_login IS NULL). NULL means never logged in.';
COMMENT ON COLUMN base.participant.suspended IS 'TRUE when every enrolment of the user in the course is suspended or disabled.';

-- daily_activity -------------------------------------------------------------

CREATE OR REPLACE TABLE base.daily_activity AS
SELECT
    CAST(l.courseid AS BIGINT) AS course_id,
    pseudo(l.userid) AS user_ref,
    CAST(epoch_ts(l.timecreated) AS DATE) AS day,
    CAST(count(*) AS INTEGER) AS events,
    CAST(count(*) FILTER (WHERE l.action = 'viewed') AS INTEGER) AS views,
    CAST(count(DISTINCT CASE WHEN CAST(l.contextlevel AS INTEGER) = 70 THEN l.contextinstanceid END) AS INTEGER) AS distinct_activities
FROM m.mdl_logstore_standard_log AS l
WHERE l.origin = 'web'
  AND CAST(l.userid AS BIGINT) > 0
  AND NOT flag(l.anonymous)
  AND l.courseid IN (SELECT course_id FROM base.course)
GROUP BY ALL;

COMMENT ON TABLE base.daily_activity IS 'One row per (course_id, user_ref, day) with at least one web event in the Moodle log. Days without activity have no row. Includes teachers: join participant on (course_id, user_ref) and filter role = ''student'' for student activity.';
COMMENT ON COLUMN base.daily_activity.course_id IS 'Course id. Join to course.course_id.';
COMMENT ON COLUMN base.daily_activity.user_ref IS 'Pseudonymous user id. Join to participant.user_ref together with course_id.';
COMMENT ON COLUMN base.daily_activity.day IS 'Calendar day (UTC).';
COMMENT ON COLUMN base.daily_activity.events IS 'Number of logged web events that day in the course (views, submissions, completions, grading, and so on).';
COMMENT ON COLUMN base.daily_activity.views IS 'Number of view events that day (course page or activity viewed).';
COMMENT ON COLUMN base.daily_activity.distinct_activities IS 'Number of distinct activities (cm_id) the user interacted with that day.';

-- activity -------------------------------------------------------------------

CREATE OR REPLACE TABLE base.activity AS
WITH instance AS (
    SELECT 'assign' AS module, id AS instance_id, name, duedate AS due_epoch FROM m.mdl_assign
    UNION ALL SELECT 'quiz', id, name, timeclose FROM m.mdl_quiz
    UNION ALL SELECT 'page', id, name, NULL FROM m.mdl_page
    UNION ALL SELECT 'forum', id, name, NULL FROM m.mdl_forum
    UNION ALL SELECT 'url', id, name, NULL FROM m.mdl_url
    UNION ALL SELECT 'resource', id, name, NULL FROM m.mdl_resource
    UNION ALL SELECT 'book', id, name, NULL FROM m.mdl_book
    UNION ALL SELECT 'label', id, name, NULL FROM m.mdl_label
)
SELECT
    CAST(cm.course AS BIGINT) AS course_id,
    CAST(cm.id AS BIGINT) AS cm_id,
    CAST(md.name AS VARCHAR) AS module,
    CAST(i.name AS VARCHAR) AS name,
    CAST(cs.section AS INTEGER) AS section,
    flag(cm.visible) AS visible,
    CAST(cm.completion AS INTEGER) > 0 AS completion_tracked,
    epoch_ts(i.due_epoch) AS due_at
FROM m.mdl_course_modules AS cm
JOIN m.mdl_modules AS md ON md.id = cm.module
LEFT JOIN m.mdl_course_sections AS cs ON cs.id = cm.section
LEFT JOIN instance AS i ON i.module = md.name AND i.instance_id = cm.instance
WHERE NOT flag(cm.deletioninprogress)
  AND cm.course IN (SELECT course_id FROM base.course);

COMMENT ON TABLE base.activity IS 'One row per activity or resource (course module) in a course. Join completion, grade_item and assignment_submission on cm_id. Order a learning path with ORDER BY section, cm_id.';
COMMENT ON COLUMN base.activity.course_id IS 'Course id. Join to course.course_id.';
COMMENT ON COLUMN base.activity.cm_id IS 'Course module id. Primary key of the activity.';
COMMENT ON COLUMN base.activity.module IS 'Activity type: ''assign'' (assignment), ''quiz'', ''page'', ''forum'', ''url'', ''resource'' (file), ''book'', ''label'' or another Moodle module name.';
COMMENT ON COLUMN base.activity.name IS 'Activity title as shown in the course, for example ''Final Project''. NULL for module types not listed in module.';
COMMENT ON COLUMN base.activity.section IS 'Course section number (0 is the general section at the top, then 1, 2, ... in course order).';
COMMENT ON COLUMN base.activity.visible IS 'TRUE when the activity is visible to students.';
COMMENT ON COLUMN base.activity.completion_tracked IS 'TRUE when completion tracking is enabled for the activity. Completion rates only make sense for tracked activities.';
COMMENT ON COLUMN base.activity.due_at IS 'Due date (UTC) for assignments, close date for quizzes. NULL when there is none.';

-- completion -----------------------------------------------------------------

CREATE OR REPLACE TABLE base.completion AS
SELECT
    CAST(cm.course AS BIGINT) AS course_id,
    CAST(cmc.coursemoduleid AS BIGINT) AS cm_id,
    pseudo(cmc.userid) AS user_ref,
    CAST(cmc.completionstate AS INTEGER) AS state,
    CAST(cmc.completionstate AS INTEGER) IN (1, 2) AS completed,
    CASE WHEN CAST(cmc.completionstate AS INTEGER) IN (1, 2) THEN epoch_ts(cmc.timemodified) END AS completed_at
FROM m.mdl_course_modules_completion AS cmc
JOIN m.mdl_course_modules AS cm ON cm.id = cmc.coursemoduleid
WHERE cm.course IN (SELECT course_id FROM base.course);

COMMENT ON TABLE base.completion IS 'One row per (cm_id, user_ref) with a completion record for a tracked activity. A missing row means the user has not completed it. Completion rate of an activity = count(DISTINCT user_ref) FILTER (WHERE completed) / number of students in participant for that course.';
COMMENT ON COLUMN base.completion.course_id IS 'Course id. Join to course.course_id.';
COMMENT ON COLUMN base.completion.cm_id IS 'Activity id. Join to activity.cm_id.';
COMMENT ON COLUMN base.completion.user_ref IS 'Pseudonymous user id. Join to participant on (course_id, user_ref).';
COMMENT ON COLUMN base.completion.state IS 'Moodle completion state: 0 incomplete, 1 complete, 2 complete with pass grade, 3 complete with fail grade.';
COMMENT ON COLUMN base.completion.completed IS 'TRUE when state is 1 or 2.';
COMMENT ON COLUMN base.completion.completed_at IS 'When the activity was completed (UTC). NULL when not completed.';

CREATE OR REPLACE TABLE base.course_completion AS
SELECT
    CAST(cc.course AS BIGINT) AS course_id,
    pseudo(cc.userid) AS user_ref,
    CAST(cc.timecompleted AS BIGINT) > 0 AS completed,
    epoch_ts(cc.timecompleted) AS completed_at
FROM m.mdl_course_completions AS cc
WHERE cc.course IN (SELECT course_id FROM base.course);

COMMENT ON TABLE base.course_completion IS 'One row per (course_id, user_ref) that Moodle tracks for course completion. Users without a row have not completed the course. Course completion rate = count(*) FILTER (WHERE completed) / number of students in participant for that course.';
COMMENT ON COLUMN base.course_completion.course_id IS 'Course id. Join to course.course_id.';
COMMENT ON COLUMN base.course_completion.user_ref IS 'Pseudonymous user id. Join to participant on (course_id, user_ref).';
COMMENT ON COLUMN base.course_completion.completed IS 'TRUE when the user completed the course.';
COMMENT ON COLUMN base.course_completion.completed_at IS 'When the course was completed (UTC). NULL when not completed.';

-- grades ---------------------------------------------------------------------

CREATE OR REPLACE TABLE base.grade_item AS
SELECT
    CAST(gi.courseid AS BIGINT) AS course_id,
    CAST(gi.id AS BIGINT) AS grade_item_id,
    CAST(cm.id AS BIGINT) AS cm_id,
    CAST(coalesce(gi.itemname, CASE gi.itemtype WHEN 'course' THEN 'Course total' WHEN 'category' THEN 'Category total' END) AS VARCHAR) AS item_name,
    CAST(gi.itemtype AS VARCHAR) AS item_type,
    CAST(gi.itemmodule AS VARCHAR) AS item_module,
    CAST(gi.grademax AS DOUBLE) AS grade_max,
    CAST(gi.grademin AS DOUBLE) AS grade_min
FROM m.mdl_grade_items AS gi
LEFT JOIN m.mdl_modules AS md ON gi.itemtype = 'mod' AND md.name = gi.itemmodule
LEFT JOIN m.mdl_course_modules AS cm ON cm.module = md.id AND cm.instance = gi.iteminstance AND cm.course = gi.courseid
WHERE gi.courseid IN (SELECT course_id FROM base.course);

COMMENT ON TABLE base.grade_item IS 'One row per gradebook item. item_type = ''mod'' for activity grades (assignments, quizzes), ''course'' for the course total, ''category'' for category totals, ''manual'' for manual items. Filter item_type = ''mod'' to compare activities.';
COMMENT ON COLUMN base.grade_item.course_id IS 'Course id. Join to course.course_id.';
COMMENT ON COLUMN base.grade_item.grade_item_id IS 'Gradebook item id. Primary key. Join to grade.grade_item_id.';
COMMENT ON COLUMN base.grade_item.cm_id IS 'Activity id for item_type = ''mod''; join to activity.cm_id. NULL for totals and manual items.';
COMMENT ON COLUMN base.grade_item.item_name IS 'Item name, usually the activity title. ''Course total'' for the course item.';
COMMENT ON COLUMN base.grade_item.item_type IS '''mod'', ''course'', ''category'' or ''manual''.';
COMMENT ON COLUMN base.grade_item.item_module IS 'Activity type for item_type = ''mod'' (''assign'', ''quiz''). NULL otherwise.';
COMMENT ON COLUMN base.grade_item.grade_max IS 'Maximum grade, in points. Divide final_grade by it for a percentage.';
COMMENT ON COLUMN base.grade_item.grade_min IS 'Minimum grade, in points.';

CREATE OR REPLACE TABLE base.grade AS
SELECT
    CAST(gi.courseid AS BIGINT) AS course_id,
    CAST(gg.itemid AS BIGINT) AS grade_item_id,
    pseudo(gg.userid) AS user_ref,
    CAST(gg.finalgrade AS DOUBLE) AS final_grade,
    CAST(gg.rawgrade AS DOUBLE) AS raw_grade,
    epoch_ts(gg.timemodified) AS graded_at
FROM m.mdl_grade_grades AS gg
JOIN m.mdl_grade_items AS gi ON gi.id = gg.itemid
WHERE gg.finalgrade IS NOT NULL
  AND gi.courseid IN (SELECT course_id FROM base.course);

COMMENT ON TABLE base.grade IS 'One row per (grade_item_id, user_ref) with a final grade. Ungraded users have no row. Join grade_item on grade_item_id for the item name and maximum.';
COMMENT ON COLUMN base.grade.course_id IS 'Course id. Join to course.course_id.';
COMMENT ON COLUMN base.grade.grade_item_id IS 'Gradebook item. Join to grade_item.grade_item_id.';
COMMENT ON COLUMN base.grade.user_ref IS 'Pseudonymous user id. Join to participant on (course_id, user_ref).';
COMMENT ON COLUMN base.grade.final_grade IS 'Final grade in points, between grade_item.grade_min and grade_item.grade_max. Use this for averages.';
COMMENT ON COLUMN base.grade.raw_grade IS 'Grade given in the activity before gradebook adjustments. Often NULL for totals.';
COMMENT ON COLUMN base.grade.graded_at IS 'Last time the grade changed (UTC).';

-- assignment_submission ------------------------------------------------------

CREATE OR REPLACE TABLE base.assignment_submission AS
SELECT
    CAST(a.course AS BIGINT) AS course_id,
    CAST(cm.id AS BIGINT) AS cm_id,
    CAST(a.id AS BIGINT) AS assignment_id,
    pseudo(s.userid) AS user_ref,
    CAST(s.status AS VARCHAR) AS status,
    CASE WHEN s.status = 'submitted' THEN epoch_ts(s.timemodified) END AS submitted_at,
    flag(s.latest) AS latest
FROM m.mdl_assign_submission AS s
JOIN m.mdl_assign AS a ON a.id = s.assignment
JOIN m.mdl_modules AS md ON md.name = 'assign'
JOIN m.mdl_course_modules AS cm ON cm.module = md.id AND cm.instance = a.id
WHERE CAST(s.userid AS BIGINT) > 0
  AND a.course IN (SELECT course_id FROM base.course);

COMMENT ON TABLE base.assignment_submission IS 'One row per assignment submission attempt. Students who never submitted have no row: to find them, take students from participant and exclude those with a row where status = ''submitted'' AND latest. Join activity on cm_id for the assignment name and due_at.';
COMMENT ON COLUMN base.assignment_submission.course_id IS 'Course id. Join to course.course_id.';
COMMENT ON COLUMN base.assignment_submission.cm_id IS 'Activity id of the assignment. Join to activity.cm_id.';
COMMENT ON COLUMN base.assignment_submission.assignment_id IS 'Moodle assignment instance id.';
COMMENT ON COLUMN base.assignment_submission.user_ref IS 'Pseudonymous user id. Join to participant on (course_id, user_ref).';
COMMENT ON COLUMN base.assignment_submission.status IS '''submitted'' (handed in), ''draft'' (started, not handed in), ''new'' (no content yet) or ''reopened''.';
COMMENT ON COLUMN base.assignment_submission.submitted_at IS 'When the submission was handed in (UTC). NULL unless status = ''submitted''.';
COMMENT ON COLUMN base.assignment_submission.latest IS 'TRUE for the latest attempt of the user. Filter latest to count each user once.';

-- export_meta ----------------------------------------------------------------

CREATE OR REPLACE TABLE base.export_meta (
    exported_at TIMESTAMP,
    source VARCHAR,
    row_counts VARCHAR
);

COMMENT ON TABLE base.export_meta IS 'One row describing this export. Data is a snapshot taken at exported_at.';
COMMENT ON COLUMN base.export_meta.exported_at IS 'When the export ran (UTC). days_since_last_access is relative to this time.';
COMMENT ON COLUMN base.export_meta.source IS 'How Moodle was read: ''mysql'' (direct) or ''parquet'' (staged dump).';
COMMENT ON COLUMN base.export_meta.row_counts IS 'JSON object with the row count of every table.';
