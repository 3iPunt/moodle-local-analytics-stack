<?php
// Adds realistic variety on top of the tool_generator courses: teachers, a tracked learning path,
// submissions, grades, completion, inactivity and backdated log events.
// Run inside the moodle container as www-data after scripts/demo-data.sh created the courses.

define('CLI_SCRIPT', true);

require('/var/www/html/config.php');
require_once($CFG->libdir . '/clilib.php');
require_once($CFG->libdir . '/gradelib.php');
require_once($CFG->libdir . '/completionlib.php');
require_once($CFG->dirroot . '/completion/criteria/completion_criteria_activity.php');
require_once($CFG->dirroot . '/completion/completion_aggregation.php');
require_once($CFG->dirroot . '/mod/assign/lib.php');
require_once($CFG->dirroot . '/mod/assign/locallib.php');

const PLUGIN = 'local_stackdemo';
const DAY = 86400;
const HOUR = 3600;

$started = microtime(true);
// Welcome and enrolment emails are noise for a demo site without a mail server.
$CFG->noemailever = true;
\core\session\manager::set_user(get_admin());

// Index order matters: teacher assignments refer to positions 1..5.
$coursedefs = [
    'DA101' => [
        'units' => ['Data cleaning', 'Exploratory analysis', 'Dashboards and reporting'],
        'curve' => [0.95, 0.93, 0.91, 0.88, 0.85, 0.81, 0.76, 0.70],
        'mean' => 74, 'submitrate' => 0.70, 'keep' => 95,
    ],
    'PROG101' => [
        'units' => ['Variables and control flow', 'Functions and modules', 'Testing and debugging'],
        'curve' => [0.94, 0.90, 0.86, 0.81, 0.75, 0.69, 0.62, 0.55],
        'mean' => 68, 'submitrate' => 0.62, 'keep' => 85,
    ],
    'STAT201' => [
        'units' => ['Descriptive statistics', 'Regression modelling', 'Survey design'],
        // Deliberate cliff on the sixth tracked activity (Unit 2).
        'curve' => [0.93, 0.91, 0.89, 0.87, 0.85, 0.15, 0.12, 0.10],
        'mean' => 55, 'submitrate' => 0.45, 'keep' => 75, 'keepinactive' => true,
    ],
    'RM301' => [
        'units' => ['Research questions', 'Qualitative methods', 'Writing up findings'],
        'curve' => [0.92, 0.86, 0.79, 0.71, 0.63, 0.55, 0.47, 0.40],
        'mean' => 63, 'submitrate' => 0.60, 'keep' => 70,
    ],
    'DB201' => [
        'units' => ['Relational modelling', 'SQL joins', 'Indexing and performance'],
        'curve' => [0.90, 0.80, 0.70, 0.60, 0.50, 0.41, 0.33, 0.25],
        'mean' => 60, 'submitrate' => 0.55, 'keep' => 60,
    ],
];

$teacherdefs = [
    ['username' => 'lmartinez', 'firstname' => 'Laura', 'lastname' => 'Martinez', 'courses' => [1, 2, 3]],
    ['username' => 'jokafor', 'firstname' => 'James', 'lastname' => 'Okafor', 'courses' => [3, 4, 5]],
    ['username' => 'schen', 'firstname' => 'Sofia', 'lastname' => 'Chen', 'courses' => [2]],
];

if (get_config(PLUGIN, 'variety_applied')) {
    cli_writeln('Variety already applied on ' . userdate(get_config(PLUGIN, 'variety_applied')) . ', nothing to do.');
    print_summary($coursedefs, $teacherdefs, $started);
    exit(0);
}
if ($DB->record_exists('user', ['username' => $teacherdefs[0]['username']])) {
    cli_error('Partial variety run detected (teachers exist but no completion flag). Reset with `make clean && make up`.');
}

$password = getenv('DEMO_USER_PASSWORD');
if (empty($password)) {
    cli_error('DEMO_USER_PASSWORD is not set.');
}

mt_srand(42);
$now = time();
$start = usergetmidnight($now) - 60 * DAY;
$generator = \core\test\phpunit\phpunit_util::get_data_generator();
$manual = enrol_get_plugin('manual');
$studentrole = $DB->get_field('role', 'id', ['shortname' => 'student'], MUST_EXIST);
$teacherrole = $DB->get_field('role', 'id', ['shortname' => 'editingteacher'], MUST_EXIST);
$admin = get_admin();
$syscontext = context_system::instance();

// Courses.
$courses = [];
$position = 0;
foreach ($coursedefs as $shortname => $def) {
    $position++;
    $course = $DB->get_record('course', ['shortname' => $shortname]);
    if (!$course) {
        cli_error("Course $shortname not found; run the generator first.");
    }
    $DB->update_record('course', (object) [
        'id' => $course->id, 'enablecompletion' => 1, 'showcompletionconditions' => 1, 'startdate' => $start,
    ]);
    $courses[$position] = (object) [
        'id' => (int) $course->id, 'shortname' => $shortname, 'def' => $def,
        'context' => context_course::instance($course->id),
        'instance' => manual_instance($course->id),
    ];
}
rebuild_course_cache(0, true);

// Global student profiles: never accessed, inactive (15-60 days) or active (0-10 days).
$studentids = array_map('intval', $DB->get_fieldset_sql(
    "SELECT id FROM {user} WHERE username LIKE 'tool\\_generator\\_%' AND deleted = 0 ORDER BY id"));
if (!$studentids) {
    cli_error('No tool_generator students found.');
}
$shuffled = $studentids;
shuffle($shuffled);
$nevercount = (int) round(count($shuffled) * 0.05);
$inactivecount = (int) round(count($shuffled) * 0.20);
$profiles = [];
foreach ($shuffled as $i => $uid) {
    if ($i < $nevercount) {
        $p = (object) ['type' => 'never', 'last' => 0, 'first' => 0];
    } else if ($i < $nevercount + $inactivecount) {
        $last = $now - randint(15 * DAY, 58 * DAY);
        $p = (object) ['type' => 'inactive', 'last' => $last, 'first' => min($start + randint(HOUR, 2 * DAY), $last - HOUR)];
    } else {
        $last = $now - randint(10 * 60, 10 * DAY);
        $p = (object) ['type' => 'active', 'last' => $last, 'first' => $start + randint(HOUR, 2 * DAY)];
    }
    $p->ability = gauss();
    $p->ip = '10.20.' . randint(0, 255) . '.' . randint(1, 254);
    $p->dayrate = 0.35 + 0.35 * rnd();
    $p->courses = [];
    $profiles[$uid] = $p;
}

// Enrolment subsets so courses differ in size; STAT201 keeps every inactive and never-accessed student.
foreach ($courses as $c) {
    $keepcount = min($c->def['keep'], count($studentids));
    $pool = $studentids;
    shuffle($pool);
    if (!empty($c->def['keepinactive'])) {
        usort($pool, fn($a, $b) => ($profiles[$a]->type === 'active') <=> ($profiles[$b]->type === 'active'));
    }
    $keep = array_slice($pool, 0, $keepcount);
    foreach (array_diff($studentids, $keep) as $uid) {
        $manual->unenrol_user($c->instance, $uid);
    }
    if (is_enrolled($c->context, $admin->id)) {
        $manual->unenrol_user($c->instance, $admin->id);
    }
    sort($keep);
    $c->students = $keep;
    foreach ($keep as $uid) {
        $profiles[$uid]->courses[] = $c->id;
    }
    $DB->execute("UPDATE {user_enrolments} SET timestart = ?, timecreated = ?, timemodified = ? WHERE enrolid = ?",
        [$start, $start - DAY, $start - DAY, $c->instance->id]);
    $DB->execute("UPDATE {role_assignments} SET timemodified = ? WHERE contextid = ?", [$start - DAY, $c->context->id]);
}

// Teachers.
$teachers = [];
foreach ($teacherdefs as $t) {
    $user = $generator->create_user([
        'username' => $t['username'], 'firstname' => $t['firstname'], 'lastname' => $t['lastname'],
        'email' => $t['username'] . '@example.edu', 'password' => $password, 'auth' => 'manual',
    ]);
    $t['id'] = (int) $user->id;
    $t['courseids'] = [];
    foreach ($t['courses'] as $pos) {
        $manual->enrol_user($courses[$pos]->instance, $user->id, $teacherrole, $start - 7 * DAY);
        $courses[$pos]->teachers[] = $t['id'];
        $t['courseids'][] = $courses[$pos]->id;
    }
    $t['last'] = $now - randint(2 * HOUR, 20 * HOUR);
    $t['ip'] = '10.10.0.' . randint(1, 254);
    $teachers[] = (object) $t;
}

// Learning path: eight tracked activities in sections 1-8, final project in section 9.
foreach ($courses as $c) {
    $u = $c->def['units'];
    $path = [
        ['page', 'Welcome and course guide'],
        ['url', 'Essential reading list'],
        ['forum', 'Introduce yourself'],
        ['page', 'Unit 1: ' . $u[0]],
        ['assign', 'Problem Set 1'],
        ['page', 'Unit 2: ' . $u[1]],
        ['quiz', 'Checkpoint quiz'],
        ['page', 'Unit 3: ' . $u[2]],
    ];
    $c->a1due = $start + 35 * DAY;
    $c->path = [];
    foreach ($path as $i => [$mod, $name]) {
        $k = $i + 1;
        $record = ['course' => $c->id, 'name' => $name, 'completion' => COMPLETION_TRACKING_AUTOMATIC];
        if ($mod === 'assign') {
            $record += [
                'completionsubmit' => 1, 'allowsubmissionsfromdate' => $start, 'duedate' => $c->a1due,
                'gradingduedate' => $c->a1due + 7 * DAY, 'assignsubmission_onlinetext_enabled' => 1,
                'submissiondrafts' => 0,
            ];
        } else {
            $record['completionview'] = 1;
        }
        if ($mod === 'url') {
            $record['externalurl'] = 'https://moodle.org/';
        }
        $instance = $generator->create_module($mod, $record, ['section' => $k]);
        $c->path[$k] = (object) [
            'mod' => $mod, 'name' => $name, 'cmid' => (int) $instance->cmid, 'instance' => $instance,
            'ctx' => context_module::instance($instance->cmid),
            'nominal' => $start + (int) ((2 + ($k - 1) * 6.5) * DAY),
        ];
    }
    $final = $generator->create_module('assign', [
        'course' => $c->id, 'name' => 'Final Project', 'allowsubmissionsfromdate' => $now - 14 * DAY,
        'duedate' => usergetmidnight($now) + 3 * DAY + 17 * HOUR, 'gradingduedate' => $now + 10 * DAY,
        'assignsubmission_onlinetext_enabled' => 1, 'submissiondrafts' => 0,
    ], ['section' => 9]);
    $c->final = (object) ['instance' => $final, 'cmid' => (int) $final->cmid, 'ctx' => context_module::instance($final->cmid)];
    for ($s = 1; $s <= 9; $s++) {
        $DB->set_field('course_sections', 'name', "Week $s", ['course' => $c->id, 'section' => $s]);
    }

    $criterion = new completion_criteria_activity();
    $criteriadata = (object) [
        'id' => $c->id, 'criteria_activity' => array_fill_keys(array_column($c->path, 'cmid'), 1),
    ];
    $criterion->update_config($criteriadata);
    $aggregation = new completion_aggregation(['course' => $c->id, 'criteriatype' => null]);
    $aggregation->setMethod(COMPLETION_AGGREGATION_ALL);
    $aggregation->save();
    $c->criteria = $DB->get_records_menu('course_completion_criteria', ['course' => $c->id], '', 'moduleinstance, id');

    $c->viewable = [];
    foreach (get_fast_modinfo($c->id)->get_cms() as $cm) {
        if (in_array($cm->modname, ['page', 'resource', 'forum', 'url'])) {
            $c->viewable[] = (object) ['mod' => $cm->modname, 'cmid' => (int) $cm->id, 'instance' => (int) $cm->instance,
                'ctx' => context_module::instance($cm->id)];
        }
    }
}
rebuild_course_cache(0, true);

// Per-course behaviour: depth along the path, submissions and grades.
$events = [];
$cmcrows = [];
$viewedrows = [];
$gradesync = [];
foreach ($courses as $c) {
    $n = count($c->students);
    $score = [];
    foreach ($c->students as $uid) {
        $p = $profiles[$uid];
        $score[$uid] = match ($p->type) {
            'never' => -10.0,
            'inactive' => 0.6 * ($p->last - $start) / ($now - $start) + 0.4 * rnd(),
            'active' => 1.0 + rnd(),
        };
    }
    arsort($score);
    $ranked = array_keys($score);
    $eligible = count(array_filter($c->students, fn($uid) => $profiles[$uid]->type !== 'never'));
    $counts = [];
    $prev = $eligible;
    foreach ($c->def['curve'] as $k => $rate) {
        $prev = min($prev, (int) round($rate * $n));
        $counts[$k + 1] = $prev;
    }
    $c->depth = [];
    foreach ($ranked as $i => $uid) {
        $d = 0;
        foreach ($counts as $k => $cnt) {
            if ($i < $cnt) {
                $d = $k;
            }
        }
        $c->depth[$uid] = $d;
    }

    $teacherid = $c->teachers[0];
    foreach ($c->students as $uid) {
        $p = $profiles[$uid];
        $d = $c->depth[$uid];
        if ($d === 0) {
            continue;
        }
        $times = completion_times($c, $p, $d);
        foreach ($times as $k => $t) {
            $step = $c->path[$k];
            $cmcrows[] = ['coursemoduleid' => $step->cmid, 'userid' => $uid, 'completionstate' => COMPLETION_COMPLETE,
                'overrideby' => null, 'timemodified' => $t];
            if ($step->mod !== 'assign') {
                $viewedrows[] = ['coursemoduleid' => $step->cmid, 'userid' => $uid, 'timecreated' => $t - 60];
            }
            $events[] = ev_module_viewed($step->mod, $step->instance->id, $step->ctx, $uid, $c->id, $t - 60, $p->ip);
        }
        $c->times[$uid] = $times;

        // Problem Set 1: submitted by everyone who reached it, all graded by the first teacher.
        if ($d >= 5) {
            $a1 = $c->path[5];
            $subtime = $times[5];
            $subid = $DB->insert_record('assign_submission', (object) [
                'assignment' => $a1->instance->id, 'userid' => $uid, 'timecreated' => $subtime - 1200,
                'timemodified' => $subtime, 'timestarted' => $subtime - 1200, 'status' => ASSIGN_SUBMISSION_STATUS_SUBMITTED,
                'groupid' => 0, 'attemptnumber' => 0, 'latest' => 1,
            ]);
            $events[] = ev_assign($a1, 'submission_status_viewed', $uid, $c->id, $subtime - 1250, $p->ip, $uid);
            $events[] = ev_assign($a1, 'assessable_submitted', $uid, $c->id, $subtime, $p->ip, $uid, $subid);
            $gradetime = min(max($c->a1due + randint(DAY, 4 * DAY), $subtime + DAY), $now - 2 * DAY);
            $grade = clampgrade($c->def['mean'] - 2 + 9 * $p->ability + 7 * gauss());
            $gradeid = $DB->insert_record('assign_grades', (object) [
                'assignment' => $a1->instance->id, 'userid' => $uid, 'timecreated' => $gradetime,
                'timemodified' => $gradetime, 'grader' => $teacherid, 'grade' => $grade, 'attemptnumber' => 0,
            ]);
            $events[] = ev_assign($a1, 'submission_graded', $teacherid, $c->id, $gradetime,
                teacher_ip($teachers, $teacherid), $uid, $gradeid);
            $gradesync[] = [$a1->instance->id, $uid, $gradetime, $subtime, 'assign'];
        }
        // Checkpoint quiz grade at the time the student completed it.
        if ($d >= 7) {
            $quiz = $c->path[7]->instance;
            $grade = clampgrade($c->def['mean'] + 6 + 9 * $p->ability + 8 * gauss());
            $DB->insert_record('quiz_grades', (object) ['quiz' => $quiz->id, 'userid' => $uid, 'grade' => $grade,
                'timemodified' => $times[7]]);
            $c->quizgrades[$uid] = ['userid' => $uid, 'rawgrade' => $grade, 'dategraded' => $times[7],
                'datesubmitted' => $times[7]];
            $gradesync[] = [$quiz->id, $uid, $times[7], $times[7], 'quiz'];
        }
    }

    // Final Project: active students only, ranked by engagement with noise.
    $candidates = [];
    foreach ($c->students as $uid) {
        if ($profiles[$uid]->type === 'active') {
            $candidates[$uid] = $score[$uid] + 0.8 * rnd();
        }
    }
    arsort($candidates);
    $submitters = array_slice(array_keys($candidates), 0, (int) round($c->def['submitrate'] * $n));
    foreach ($submitters as $uid) {
        $p = $profiles[$uid];
        $subtime = randint(max($now - 10 * DAY, $p->first + HOUR), $p->last);
        $subid = $DB->insert_record('assign_submission', (object) [
            'assignment' => $c->final->instance->id, 'userid' => $uid, 'timecreated' => $subtime - 3600,
            'timemodified' => $subtime, 'timestarted' => $subtime - 3600, 'status' => ASSIGN_SUBMISSION_STATUS_SUBMITTED,
            'groupid' => 0, 'attemptnumber' => 0, 'latest' => 1,
        ]);
        $events[] = ev_module_viewed('assign', $c->final->instance->id, $c->final->ctx, $uid, $c->id, $subtime - 3700, $p->ip);
        $events[] = ev_assign($c->final, 'submission_status_viewed', $uid, $c->id, $subtime - 3650, $p->ip, $uid);
        $events[] = ev_assign($c->final, 'assessable_submitted', $uid, $c->id, $subtime, $p->ip, $uid, $subid);
    }
    $c->submitters = count($submitters);
}

// Completion rows, then the matching completion events and course completion records.
foreach (array_chunk($cmcrows, 1000) as $chunk) {
    $DB->insert_records('course_modules_completion', $chunk);
}
foreach (array_chunk($viewedrows, 1000) as $chunk) {
    $DB->insert_records('course_modules_viewed', $chunk);
}
foreach ($courses as $c) {
    $cmids = array_column($c->path, 'cmid');
    [$insql, $params] = $DB->get_in_or_equal($cmids);
    $rs = $DB->get_recordset_select('course_modules_completion', "coursemoduleid $insql", $params);
    $cmctx = [];
    foreach ($c->path as $step) {
        $cmctx[$step->cmid] = $step->ctx;
    }
    foreach ($rs as $r) {
        $events[] = ev($cmctx[$r->coursemoduleid], '\core\event\course_module_completion_updated', 'core', 'updated',
            'course_module_completion', 'course_modules_completion', $r->id, 'u', 2, $r->userid, $c->id, $r->userid,
            ['relateduserid' => (int) $r->userid, 'overrideby' => null, 'completionstate' => 1], $r->timemodified,
            $profiles[$r->userid]->ip);
    }
    $rs->close();

    $DB->delete_records('course_completions', ['course' => $c->id]);
    $DB->delete_records('course_completion_crit_compl', ['course' => $c->id]);
    $ccrows = [];
    $critrows = [];
    $c->completed = 0;
    foreach ($c->students as $uid) {
        $p = $profiles[$uid];
        $times = $c->times[$uid] ?? [];
        $completed = count($times) === 8 ? $times[8] + 300 : null;
        $c->completed += $completed ? 1 : 0;
        $ccrows[] = ['userid' => $uid, 'course' => $c->id, 'timeenrolled' => $start,
            'timestarted' => $p->first ?: 0, 'timecompleted' => $completed, 'reaggregate' => 0];
        foreach ($times as $k => $t) {
            $critrows[] = ['userid' => $uid, 'course' => $c->id, 'criteriaid' => $c->criteria[$c->path[$k]->cmid],
                'gradefinal' => null, 'unenroled' => null, 'timecompleted' => $t];
        }
    }
    $DB->insert_records('course_completions', $ccrows);
    foreach (array_chunk($critrows, 1000) as $chunk) {
        $DB->insert_records('course_completion_crit_compl', $chunk);
    }
}

// Gradebook: push activity grades, then backdate them.
foreach ($courses as $c) {
    $a1 = $DB->get_record('assign', ['id' => $c->path[5]->instance->id]);
    $a1->cmidnumber = '';
    assign_update_grades($a1);
    if (!empty($c->quizgrades)) {
        grade_update('mod/quiz', $c->id, 'mod', 'quiz', $c->path[7]->instance->id, 0, $c->quizgrades);
    }
    grade_regrade_final_grades($c->id);
}
foreach ($gradesync as [$instanceid, $uid, $gradetime, $subtime, $mod]) {
    $itemid = grade_itemid($mod, $instanceid);
    $DB->execute("UPDATE {grade_grades} SET timecreated = ?, timemodified = ? WHERE itemid = ? AND userid = ?",
        [$subtime, $gradetime, $itemid, $uid]);
}

// Daily browsing activity, logins and last access.
$lastcourseaccess = [];
foreach ($profiles as $uid => $p) {
    if ($p->type === 'never' || !$p->courses) {
        continue;
    }
    $logins = [];
    for ($day = usergetmidnight($p->first); $day <= $p->last; $day += DAY) {
        if (rnd() > $p->dayrate) {
            continue;
        }
        $t = $day + randint(8 * HOUR, 21 * HOUR);
        if ($t < $p->first || $t > $p->last) {
            continue;
        }
        $logins[] = $t;
        $events[] = ev_login($uid, $t, $p->ip);
        foreach ($p->courses as $cid) {
            if (rnd() > 0.65) {
                continue;
            }
            $c = course_by_id($courses, $cid);
            $vt = min($t + randint(60, 1200), $p->last);
            $events[] = ev_course_viewed($c, $uid, $vt, $p->ip);
            for ($v = randint(0, 4); $v > 0; $v--) {
                $cm = $c->viewable[array_rand($c->viewable)];
                $events[] = ev_module_viewed($cm->mod, $cm->instance, $cm->ctx, $uid, $c->id,
                    min($vt + randint(60, 900), $p->last), $p->ip);
            }
        }
    }
    // The last access is always a login followed by a course view.
    $c = course_by_id($courses, $p->courses[array_rand($p->courses)]);
    $events[] = ev_login($uid, $p->last - 120, $p->ip);
    $events[] = ev_course_viewed($c, $uid, $p->last, $p->ip);
    $logins[] = $p->last - 120;
    sort($logins);
    $p->currentlogin = end($logins);
    $p->lastlogin = count($logins) > 1 ? $logins[count($logins) - 2] : 0;
}
foreach ($teachers as $t) {
    $logins = [];
    for ($day = $start - 2 * DAY; $day <= $t->last; $day += DAY) {
        if (rnd() > 0.7) {
            continue;
        }
        $lt = min($day + randint(8 * HOUR, 19 * HOUR), $t->last);
        $logins[] = $lt;
        $events[] = ev_login($t->id, $lt, $t->ip);
        foreach ($t->courseids as $cid) {
            if (rnd() > 0.6) {
                continue;
            }
            $events[] = ev_course_viewed(course_by_id($courses, $cid), $t->id, min($lt + randint(60, 1800), $t->last), $t->ip);
        }
    }
    $events[] = ev_login($t->id, $t->last - 60, $t->ip);
    $events[] = ev_course_viewed(course_by_id($courses, $t->courseids[0]), $t->id, $t->last, $t->ip);
    $logins[] = $t->last - 60;
    sort($logins);
    $profiles[$t->id] = (object) ['type' => 'teacher', 'first' => $logins[0], 'last' => $t->last,
        'currentlogin' => end($logins), 'lastlogin' => $logins[count($logins) - 2] ?? 0];
}

usort($events, fn($a, $b) => $a['timecreated'] <=> $b['timecreated']);
foreach ($events as $e) {
    if ($e['courseid']) {
        $key = $e['userid'] . ':' . $e['courseid'];
        $lastcourseaccess[$key] = max($lastcourseaccess[$key] ?? 0, $e['timecreated']);
    }
}
foreach (array_chunk($events, 2000) as $chunk) {
    $DB->insert_records('logstore_standard_log', $chunk);
}

$courseids = array_column($courses, 'id');
[$insql, $params] = $DB->get_in_or_equal($courseids);
$DB->delete_records_select('user_lastaccess', "courseid $insql", $params);
$larows = [];
foreach ($lastcourseaccess as $key => $time) {
    [$uid, $cid] = array_map('intval', explode(':', $key));
    $larows[] = ['userid' => $uid, 'courseid' => $cid, 'timeaccess' => $time];
}
$DB->insert_records('user_lastaccess', $larows);
foreach ($profiles as $uid => $p) {
    $DB->update_record('user', (object) [
        'id' => $uid, 'firstaccess' => $p->first, 'lastaccess' => $p->last,
        'lastlogin' => $p->lastlogin ?? 0, 'currentlogin' => $p->currentlogin ?? 0,
    ]);
}

set_config('variety_applied', $now, PLUGIN);
purge_caches(['muc' => true]);
cli_writeln('Teachers (password from DEMO_USER_PASSWORD):');
foreach ($teachers as $t) {
    $names = array_map(fn($cid) => course_by_id($courses, $cid)->shortname, $t->courseids);
    cli_writeln(sprintf('  %-10s %s %s: %s', $t->username, $t->firstname, $t->lastname, implode(', ', $names)));
}
print_summary($coursedefs, $teacherdefs, $started);

// Helpers.

function rnd(): float {
    return mt_rand() / mt_getrandmax();
}

function randint(int $min, int $max): int {
    return $max <= $min ? $min : mt_rand($min, $max);
}

function gauss(): float {
    $u1 = max(rnd(), 1e-9);
    return sqrt(-2 * log($u1)) * cos(2 * M_PI * rnd());
}

function clampgrade(float $g): float {
    return (float) max(5, min(100, round($g)));
}

function manual_instance(int $courseid): stdClass {
    foreach (enrol_get_instances($courseid, true) as $instance) {
        if ($instance->enrol === 'manual') {
            return $instance;
        }
    }
    throw new coding_exception("No manual enrolment instance in course $courseid");
}

function course_by_id(array $courses, int $id): stdClass {
    foreach ($courses as $c) {
        if ($c->id === $id) {
            return $c;
        }
    }
    throw new coding_exception("Unknown course $id");
}

function teacher_ip(array $teachers, int $id): string {
    foreach ($teachers as $t) {
        if ($t->id === $id) {
            return $t->ip;
        }
    }
    return '10.10.0.1';
}

function grade_itemid(string $mod, int $instanceid): int {
    global $DB;
    static $cache = [];
    return $cache["$mod:$instanceid"] ??= (int) $DB->get_field('grade_items', 'id',
        ['itemtype' => 'mod', 'itemmodule' => $mod, 'iteminstance' => $instanceid, 'itemnumber' => 0], MUST_EXIST);
}

/**
 * Completion timestamps for the first $depth path steps: nominal schedule with jitter,
 * compressed proportionally into the student's active window when they stopped earlier.
 */
function completion_times(stdClass $c, stdClass $p, int $depth): array {
    $times = [];
    $prev = $p->first;
    foreach (range(1, $depth) as $k) {
        $times[$k] = $c->path[$k]->nominal + randint(0, 3 * DAY);
    }
    if ($times[$depth] > $p->last - HOUR) {
        foreach (range(1, $depth) as $k) {
            $times[$k] = $p->first + (int) (($p->last - HOUR - $p->first) * $k / ($depth + 1));
        }
    }
    foreach ($times as $k => $t) {
        $times[$k] = $prev = max($t, $prev + 600);
    }
    return $times;
}

function ev(context $ctx, string $eventname, string $component, string $action, string $target, ?string $objecttable,
        ?int $objectid, string $crud, int $edulevel, int $userid, int $courseid, ?int $relateduserid, ?array $other,
        int $time, string $ip): array {
    return [
        'eventname' => $eventname, 'component' => $component, 'action' => $action, 'target' => $target,
        'objecttable' => $objecttable, 'objectid' => $objectid, 'crud' => $crud, 'edulevel' => $edulevel,
        'contextid' => $ctx->id, 'contextlevel' => $ctx->contextlevel, 'contextinstanceid' => $ctx->instanceid,
        'userid' => $userid, 'courseid' => $courseid, 'relateduserid' => $relateduserid, 'anonymous' => 0,
        'other' => json_encode($other), 'timecreated' => $time, 'origin' => 'web', 'ip' => $ip, 'realuserid' => null,
    ];
}

function ev_login(int $uid, int $time, string $ip): array {
    static $usernames = [];
    global $DB;
    $usernames[$uid] ??= $DB->get_field('user', 'username', ['id' => $uid]);
    return ev(context_system::instance(), '\core\event\user_loggedin', 'core', 'loggedin', 'user', 'user', $uid, 'r', 0,
        $uid, 0, null, ['username' => $usernames[$uid]], $time, $ip);
}

function ev_course_viewed(stdClass $c, int $uid, int $time, string $ip): array {
    return ev($c->context, '\core\event\course_viewed', 'core', 'viewed', 'course', null, null, 'r', 2,
        $uid, $c->id, null, null, $time, $ip);
}

function ev_module_viewed(string $mod, int $instanceid, context $ctx, int $uid, int $courseid, int $time, string $ip): array {
    return ev($ctx, "\\mod_{$mod}\\event\\course_module_viewed", "mod_$mod", 'viewed', 'course_module', $mod, $instanceid,
        'r', 2, $uid, $courseid, null, null, $time, $ip);
}

function ev_assign(stdClass $step, string $type, int $uid, int $courseid, int $time, string $ip, int $relateduserid,
        ?int $objectid = null): array {
    $assignid = (int) $step->instance->id;
    return match ($type) {
        'submission_status_viewed' => ev($step->ctx, '\mod_assign\event\submission_status_viewed', 'mod_assign', 'viewed',
            'submission_status', null, null, 'r', 0, $uid, $courseid, null, ['assignid' => $assignid], $time, $ip),
        'assessable_submitted' => ev($step->ctx, '\mod_assign\event\assessable_submitted', 'mod_assign', 'submitted',
            'assessable', 'assign_submission', $objectid, 'u', 2, $uid, $courseid, $relateduserid,
            ['submission_editable' => false], $time, $ip),
        'submission_graded' => ev($step->ctx, '\mod_assign\event\submission_graded', 'mod_assign', 'graded',
            'submission', 'assign_grades', $objectid, 'u', 1, $uid, $courseid, $relateduserid, null, $time, $ip),
    };
}

function print_summary(array $coursedefs, array $teacherdefs, float $started): void {
    global $DB;
    cli_heading('Demo data summary');
    $totalcmc = 0;
    $totalgrades = 0;
    foreach (array_keys($coursedefs) as $shortname) {
        $course = $DB->get_record('course', ['shortname' => $shortname], 'id, fullname', MUST_EXIST);
        $ctx = context_course::instance($course->id);
        $students = count_role_users($DB->get_field('role', 'id', ['shortname' => 'student']), $ctx);
        $teachers = implode(', ', array_map(fn($u) => $u->username,
            get_role_users($DB->get_field('role', 'id', ['shortname' => 'editingteacher']), $ctx, false, 'u.id, u.username')));
        $activities = $DB->count_records('course_modules', ['course' => $course->id]);
        $tracked = $DB->count_records_select('course_modules', 'course = ? AND completion > 0', [$course->id]);
        $cmc = $DB->count_records_sql("SELECT COUNT(1) FROM {course_modules_completion} cmc
            JOIN {course_modules} cm ON cm.id = cmc.coursemoduleid WHERE cm.course = ? AND cmc.completionstate > 0",
            [$course->id]);
        $grades = $DB->count_records_sql("SELECT COUNT(1) FROM {grade_grades} gg JOIN {grade_items} gi ON gi.id = gg.itemid
            WHERE gi.courseid = ? AND gi.itemtype = 'mod' AND gg.finalgrade IS NOT NULL", [$course->id]);
        $completed = $DB->count_records_select('course_completions', 'course = ? AND timecompleted IS NOT NULL', [$course->id]);
        $totalcmc += $cmc;
        $totalgrades += $grades;
        cli_writeln(sprintf('%-8s id=%-3d students=%-3d completed=%-3d (%2d%%) activities=%-3d tracked=%d teachers=%s',
            $shortname, $course->id, $students, $completed, $students ? round(100 * $completed / $students) : 0,
            $activities, $tracked, $teachers ?: '-'));
    }
    [$insql, $params] = $DB->get_in_or_equal(array_column($teacherdefs, 'username'));
    $teachercount = $DB->count_records_select('user', "username $insql", $params);
    $log = $DB->get_record_sql("SELECT COUNT(1) AS c, MIN(timecreated) AS mn, MAX(timecreated) AS mx
        FROM {logstore_standard_log} WHERE origin = 'web'");
    cli_writeln("teachers=$teachercount activity_grades=$totalgrades activity_completions=$totalcmc");
    cli_writeln(sprintf('web log rows=%d from %s to %s', $log->c, $log->mn ? date('Y-m-d', $log->mn) : '-',
        $log->mx ? date('Y-m-d', $log->mx) : '-'));
    cli_writeln(sprintf('time=%.1fs', microtime(true) - $started));
}
