#!/usr/bin/env bash
# Generates the demo dataset: five tool_generator courses, then scripts/moodle/variety.php,
# then refreshes the analytics export.
# Safe to re-run: existing courses are skipped and variety.php exits once applied.
set -euo pipefail

cd "$(dirname "$0")/.."

[ -f .env ] || { echo ".env is missing, run make env" >&2; exit 1; }

env_value() { awk -v key="$1" 'index($0, key "=") == 1 {print substr($0, length(key) + 2)}' "$2"; }

DEMO_USER_PASSWORD="$(env_value DEMO_USER_PASSWORD .env)"
if [ -z "$DEMO_USER_PASSWORD" ]; then
    DEMO_USER_PASSWORD="$(env_value DEMO_USER_PASSWORD .env.example)"
    echo "DEMO_USER_PASSWORD not in .env, using the .env.example value"
fi

GENERATOR_SIZE="${GENERATOR_SIZE:-S}"
COURSES=(
    "DA101|Data Analysis 101"
    "PROG101|Introduction to Programming"
    "STAT201|Statistics for Social Sciences"
    "RM301|Research Methods"
    "DB201|Databases"
)

moodle() { docker compose exec -T "$@"; }
as_www() { moodle -e DEMO_USER_PASSWORD="$DEMO_USER_PASSWORD" moodle runuser -u www-data -- "$@"; }

course_exists() {
    as_www php -r '
        define("CLI_SCRIPT", true);
        require "/var/www/html/config.php";
        exit($DB->record_exists("course", ["shortname" => $argv[1]]) ? 0 : 1);
    ' -- "$1"
}

total_start=$SECONDS
gen_start=$SECONDS
for entry in "${COURSES[@]}"; do
    shortname="${entry%%|*}"
    fullname="${entry#*|}"
    if course_exists "$shortname"; then
        echo "Course $shortname already exists, skipping generator"
        continue
    fi
    echo "Generating $shortname ($fullname), size $GENERATOR_SIZE"
    as_www php public/admin/tool/generator/cli/maketestcourse.php \
        --shortname="$shortname" --fullname="$fullname" --size="$GENERATOR_SIZE" \
        --filesizelimit=65536 --bypasscheck --quiet
done
gen_time=$((SECONDS - gen_start))

variety_start=$SECONDS
as_www php /opt/stack/scripts/variety.php
variety_time=$((SECONDS - variety_start))

echo "Running cron once and purging caches"
as_www php admin/cli/cron.php --keep-alive=0 >/dev/null
as_www php admin/cli/purge_caches.php

echo "Exporting to DuckDB so the analytics service serves the new data"
export_start=$SECONDS
docker compose exec -T analytics python -m app.export
export_time=$((SECONDS - export_start))

echo "Timings: generator ${gen_time}s, variety ${variety_time}s, export ${export_time}s, total $((SECONDS - total_start))s"
