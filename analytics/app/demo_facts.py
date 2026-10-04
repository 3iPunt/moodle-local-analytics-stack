"""The six talk questions and checkers for the facts in docs/demo-data.md.

A checker receives the columns and rows of an answer plus the course shortnames in
scope and says whether the answer states the documented facts. Checkers are lenient
about shape (a list of students or per-course counts both pass) and strict about
numbers.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

COURSE_IDS = {"DA101": 2, "PROG101": 3, "STAT201": 4, "RM301": 5, "DB201": 6}

STUDENTS = {"DA101": 95, "PROG101": 85, "STAT201": 75, "RM301": 70, "DB201": 60}
NOT_LOGGED_IN_14 = {"DA101": 23, "PROG101": 20, "STAT201": 25, "RM301": 16, "DB201": 11}
NOT_SUBMITTED = {"DA101": 28, "PROG101": 32, "STAT201": 41, "RM301": 28, "DB201": 27}
GRADES = {
    "DA101": {"Problem Set 1": 72.5, "Checkpoint quiz": 80.7},
    "PROG101": {"Problem Set 1": 66.6, "Checkpoint quiz": 74.1},
    "STAT201": {"Problem Set 1": 52.2, "Checkpoint quiz": 67.6},
    "RM301": {"Problem Set 1": 61.4, "Checkpoint quiz": 69.0},
    "DB201": {"Problem Set 1": 56.8, "Checkpoint quiz": 66.6},
}
COMPLETION = {"DA101": (67, 70.5), "PROG101": (47, 55.3), "RM301": (28, 40.0), "DB201": (15, 25.0), "STAT201": (8, 10.7)}
DROP_OFF_ACTIVITY = "Unit 2: Regression modelling"

_HEX_RE = re.compile(r"^[0-9a-f]{16,}$")

Rows = Sequence[Sequence[Any]]
Checker = Callable[[list[str], Rows, list[str]], bool]


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _close(value: Any, expected: float, tol: float = 0.11) -> bool:
    x = _num(value)
    if x is None:
        return False
    return abs(x - expected) <= tol or abs(100.0 * x - expected) <= tol


def _row_has(row: Sequence[Any], expected: float, tol: float = 0.11) -> bool:
    return any(_close(v, expected, tol) for v in row)


def _course_of(row: Sequence[Any], scope: Iterable[str]) -> str | None:
    for value in row:
        if isinstance(value, str) and value in scope:
            return value
    return None


def _user_column(rows: Rows) -> int | None:
    if not rows:
        return None
    for i, value in enumerate(rows[0]):
        if isinstance(value, str) and _HEX_RE.match(value):
            return i
    return None


def _rows_by_course(rows: Rows, scope: list[str]) -> dict[str, list[Sequence[Any]]]:
    grouped: dict[str, list[Sequence[Any]]] = {}
    for row in rows:
        course = _course_of(row, scope)
        if course:
            grouped.setdefault(course, []).append(row)
    return grouped


def check_courses(columns: list[str], rows: Rows, scope: list[str]) -> bool:
    grouped = _rows_by_course(rows, scope)
    return set(grouped) == set(scope) and all(
        any(_row_has(r, STUDENTS[c], 0) for r in grouped[c]) for c in scope
    )


def _per_course_people(rows: Rows, scope: list[str], expected: dict[str, int], distinct_total: int | None) -> bool:
    user = _user_column(rows)
    grouped = _rows_by_course(rows, scope)
    if user is not None:
        if grouped:
            return all(len({r[user] for r in grouped.get(c, [])}) == expected[c] for c in scope)
        return distinct_total is not None and len({r[user] for r in rows}) == distinct_total
    if grouped:
        return all(any(_row_has(r, expected[c], 0) for r in grouped.get(c, [])) for c in scope)
    return distinct_total is not None and len(rows) == 1 and _row_has(rows[0], distinct_total, 0)


def check_not_logged_in(columns: list[str], rows: Rows, scope: list[str]) -> bool:
    # STAT201 keeps every inactive student, so with it in scope there are 25 distinct ones.
    distinct = 25 if "STAT201" in scope else None
    user = _user_column(rows)
    if user is not None and distinct is not None and len({r[user] for r in rows}) == distinct:
        return True
    return _per_course_people(rows, scope, NOT_LOGGED_IN_14, None)


def check_not_submitted(columns: list[str], rows: Rows, scope: list[str]) -> bool:
    return _per_course_people(rows, scope, NOT_SUBMITTED, sum(NOT_SUBMITTED[c] for c in scope))


def check_grades(columns: list[str], rows: Rows, scope: list[str]) -> bool:
    grouped = _rows_by_course(rows, scope)
    for course in scope:
        for item, avg in GRADES[course].items():
            if not any(item in r and _row_has(r, avg, 0.051) for r in grouped.get(course, [])):
                return False
    return True


def check_drop_off(columns: list[str], rows: Rows, scope: list[str]) -> bool:
    if "STAT201" not in scope or not rows:
        return False
    return any(isinstance(v, str) and v.startswith(DROP_OFF_ACTIVITY) for v in rows[0])


def check_compare(columns: list[str], rows: Rows, scope: list[str]) -> bool:
    grouped = _rows_by_course(rows, scope)
    if set(grouped) != set(scope):
        return False
    return all(
        any(_row_has(r, COMPLETION[c][1]) or _row_has(r, COMPLETION[c][0], 0) for r in grouped[c]) for c in scope
    )


@dataclass(frozen=True)
class DemoQuestion:
    example_id: str
    question: str
    check: Checker
    # Same intent in other words. The talk questions are also few-shot examples, so the
    # model can copy their SQL; the paraphrase measures what it does on its own.
    paraphrase: str


DEMO_QUESTIONS = (
    DemoQuestion(
        "courses_students",
        "Which courses do I teach, and how many students are in each?",
        check_courses,
        "List my courses with the number of enrolled students",
    ),
    DemoQuestion(
        "not_logged_in_14",
        "Which students have not logged in for 14 days?",
        check_not_logged_in,
        "Show the students who have not been on the site in the last two weeks",
    ),
    DemoQuestion(
        "not_submitted_this_week",
        "Who has not submitted the assignment due this week?",
        check_not_submitted,
        "Which students still have to hand in the assignment that is due in the next few days?",
    ),
    DemoQuestion(
        "average_grade_per_item",
        "What is the average grade for each graded item in my course?",
        check_grades,
        "Show the mean score of every gradebook activity in each of my courses",
    ),
    DemoQuestion(
        "drop_off",
        "Which activity has the highest drop-off?",
        check_drop_off,
        "At which step of the course path do we lose the most students?",
    ),
    DemoQuestion(
        "compare_completion",
        "Compare completion across my courses and explain the differences",
        check_compare,
        "How do course completion rates differ between my courses, and why?",
    ),
)


def scope_names(course_ids: Iterable[int]) -> list[str]:
    by_id = {v: k for k, v in COURSE_IDS.items()}
    return [by_id[i] for i in course_ids if i in by_id]
