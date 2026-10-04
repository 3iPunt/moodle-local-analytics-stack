# Demo data

`make demo-data` builds the dataset the talk uses. It runs `scripts/demo-data.sh`, which:

1. Creates five courses with Moodle's own generator (`public/admin/tool/generator/cli/maketestcourse.php --size=S`). Courses whose shortname already exists are skipped.
2. Runs `scripts/moodle/variety.php` inside the moodle container (mounted read-only at `/opt/stack/scripts`).
3. Runs cron once and purges caches.

The run is idempotent. variety.php writes `local_stackdemo/variety_applied` to `mdl_config_plugins` when it finishes and exits early on later runs, printing the same summary. If it ever fails halfway, reset with `make clean && make up && make demo-data`.

Every number below comes from SQL run against the database after a clean `make clean && make up && make demo-data` on 2026-10-04, using the read-only `ANALYTICS_DB_USER`. Dates are relative to the run time, so absolute timestamps will differ on another day, but the counts and percentages are the same: everything is seeded with `mt_srand(42)`.

## What the generator creates

Size S in Moodle 5.3 (`tool_generator_course_backend`) creates per course: 10 sections, 10 assignments ("Assignment 1" to "Assignment 10", no due date, never graded), 50 pages, one resource with 64 small files, 2 resources with big files (capped with `--filesizelimit=65536`), and one forum with 10 discussions of 2 posts. It enrols 100 students as `student`.

The students are shared. The generator looks for users named `tool_generator_000001` and up, and creates only the missing ones, so all five courses enrol the same 100 users. It also enrols the admin as `editingteacher` in each course (`enroladminnewcourse`). None of the generated activities has completion tracking. Course `startdate` is set to today.

Size S takes about 3 seconds per course. Size M would add 1000 students and 100 graded assignments per course, which buries the patterns the talk needs, so S is used.

## What variety.php adds

- Course start date moved to 60 days ago, completion enabled, enrolments backdated.
- Students unenrolled from some courses so sizes differ: DA101 95, PROG101 85, STAT201 75, RM301 70, DB201 60. STAT201 keeps every inactive and never-seen student. Of the 100 students, 5 are in 2 courses, 25 in 3, 50 in 4 and 20 in all 5.
- Admin unenrolled from the five courses.
- Three teachers, enrolled as `editingteacher`. All share the password in `DEMO_USER_PASSWORD` (default `Demo.Teacher.2026`, from `.env.example`).
- A tracked path in sections 1 to 8 of every course, then a final assignment in section 9:

| Section | Activity | Completion rule |
|---|---|---|
| 1 | Welcome and course guide (page) | view |
| 2 | Essential reading list (url) | view |
| 3 | Introduce yourself (forum) | view |
| 4 | Unit 1: (page, topic per course) | view |
| 5 | Problem Set 1 (assign, due 25 days ago) | submit |
| 6 | Unit 2: (page) | view |
| 7 | Checkpoint quiz (quiz, graded out of 100) | view |
| 8 | Unit 3: (page) | view |
| 9 | Final Project (assign, due in 3 days) | none |

  Course completion requires all eight tracked activities (aggregation ALL). Sections are renamed "Week 1" to "Week 9".
- Completion rows (`course_modules_completion`, `course_modules_viewed`, `course_completion_crit_compl`, `course_completions`) with backdated times. Each student gets a depth along the path; students are ranked by engagement, so inactive students reach less far.
- Problem Set 1: everyone who reached step 5 submitted, and the course's first teacher graded every submission. Grades go through `assign_update_grades()`.
- Checkpoint quiz: a grade for everyone who completed it, written to `quiz_grades` and pushed with `grade_update()`. There are no `quiz_attempts` rows, so the quiz reports in Moodle show no attempts.
- Final Project: submissions only from recently active students, in the last 10 days. Nothing is graded yet.
- Access profile per student: 5 never logged in (`lastaccess = 0`, no `user_lastaccess` rows), 20 inactive (last access 15 to 58 days ago), 75 active (last access within 10 days).
- Backdated rows in `logstore_standard_log` with `origin = 'web'`: logins, course views, module views, completion updates, submission views, submissions and teacher grading events. `other` is JSON, matching `logstore_standard | jsonformat = 1`. No student has any event after their `lastaccess`.

## Expected answers

### 1. Which courses do I teach, and how many students are in each?

| Teacher | Username | Courses (students) |
|---|---|---|
| Laura Martinez | lmartinez | DA101 Data Analysis 101 (95), PROG101 Introduction to Programming (85), STAT201 Statistics for Social Sciences (75) |
| James Okafor | jokafor | STAT201 (75), RM301 Research Methods (70), DB201 Databases (60) |
| Sofia Chen | schen | PROG101 (85) |

STAT201 has two teachers (Laura and James), PROG101 has two (Laura and Sofia). The other courses have one each.

### 2. Which students have not logged in for 14 days?

25 distinct students: 5 never logged in and 20 last seen 15 to 58 days ago. Per course:

| Course | Students | Never | Inactive 15+ days | Total | Share |
|---|---|---|---|---|---|
| DA101 | 95 | 5 | 18 | 23 | 24.2% |
| PROG101 | 85 | 3 | 17 | 20 | 23.5% |
| STAT201 | 75 | 5 | 20 | 25 | 33.3% |
| RM301 | 70 | 4 | 12 | 16 | 22.9% |
| DB201 | 60 | 4 | 7 | 11 | 18.3% |

None of these students has a log event in the last 14 days. A query that only checks `user_lastaccess` misses the 5 who never logged in, since they have no row there.

### 3. Who has not submitted the assignment due this week?

"Final Project" in every course, due 3 days after the run.

| Course | Students | Submitted | Not submitted |
|---|---|---|---|
| DA101 | 95 | 67 | 28 |
| PROG101 | 85 | 53 | 32 |
| STAT201 | 75 | 34 | 41 |
| RM301 | 70 | 42 | 28 |
| DB201 | 60 | 33 | 27 |

Overall 229 of 385 enrolments submitted (59.5%). Students who submitted have a row in `assign_submission` with `status = 'submitted'`; the rest have no row.

### 4. What is the average grade for each graded item in my course?

Only two items per course have grades. The ten generator assignments and Final Project are graded items with no grades.

| Course | Problem Set 1 (n, avg) | Checkpoint quiz (n, avg) |
|---|---|---|
| DA101 | 81, 72.5 | 72, 80.7 |
| PROG101 | 64, 66.6 | 53, 74.1 |
| STAT201 | 64, 52.2 | 9, 67.6 |
| RM301 | 44, 61.4 | 33, 69.0 |
| DB201 | 30, 56.8 | 20, 66.6 |

Both items are out of 100. The quiz averages higher than the problem set in every course. STAT201 has the lowest problem set average.

### 5. Which activity has the highest drop-off?

STAT201 "Unit 2: Regression modelling" (section 6). Completion goes from 85.3% on Problem Set 1 to 14.7% on Unit 2, a drop of 70.6 points. 64 students completed the problem set and only 11 opened Unit 2.

STAT201 completion along the path: 93.3, 90.7, 89.3, 86.7, 85.3, 14.7, 12.0, 10.7.

The other courses decline gradually. The largest single step outside STAT201 is about 10 points (DB201, 90.0 to 80.0 and 80.0 to 70.0).

### 6. Compare completion across my courses and explain the differences

| Course | Students | Completed | Rate | Not seen in 14 days | Problem Set 1 avg |
|---|---|---|---|---|---|
| DA101 | 95 | 67 | 70.5% | 24.2% | 72.5 |
| PROG101 | 85 | 47 | 55.3% | 23.5% | 66.6 |
| RM301 | 70 | 28 | 40.0% | 22.9% | 61.4 |
| DB201 | 60 | 15 | 25.0% | 18.3% | 56.8 |
| STAT201 | 75 | 8 | 10.7% | 33.3% | 52.2 |

The explanations the data supports:

- STAT201 is last because of the Unit 2 cliff: 85% get through Problem Set 1, but only 15% go past Unit 2, and all eight activities are required to complete the course. It also has the highest share of inactive students (a third of the class) and the lowest grades.
- DA101, PROG101, RM301 and DB201 lose students steadily along the path with no single bad step. The decline is steeper in each of them in that order: DB201 starts at 90% on the first activity and loses about 8 to 10 points per step.
- Inactivity does not explain the gap between the other four courses. DB201 has the lowest inactive share (18.3%) and still the second-lowest completion, so the difference there comes from active students who stop partway.

For Laura: DA101 70.5%, PROG101 55.3%, STAT201 10.7%. For James: RM301 40.0%, DB201 25.0%, STAT201 10.7%.

## Volumes

- 5 courses, 100 students, 3 teachers, 73 activities per course (8 tracked).
- 470 activity grades, 2172 activity completions, 165 course completions.
- 26757 web log rows from 2026-08-03 to 2026-10-04, plus about 3500 `cli` rows written by the generator and variety.php at run time.
- Timing on the reference machine: generator 13 s, variety.php 26 s, cron and purge included, 41 s total. A second run takes 3 s.
