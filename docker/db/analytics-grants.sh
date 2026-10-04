#!/usr/bin/env bash
# Creates the read-only analytics user and grants SELECT on exactly the columns listed
# in analytics-tables.txt (no password, email, name or IP column is ever readable). Idempotent: every run revokes everything and grants again, and
# resets the password to ANALYTICS_DB_PASSWORD.
#
# Runs as the one-shot compose service `db-grants` after Moodle is installed, because
# MySQL refuses a table-level GRANT on a table that does not exist yet (error 1146),
# so it cannot run from docker-entrypoint-initdb.d on a fresh volume.
set -euo pipefail

: "${MYSQL_HOST:=db}"
: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD is required}"
: "${MYSQL_DATABASE:?MYSQL_DATABASE is required}"
: "${ANALYTICS_DB_USER:?ANALYTICS_DB_USER is required}"
: "${ANALYTICS_DB_PASSWORD:?ANALYTICS_DB_PASSWORD is required}"
TABLES_FILE="${TABLES_FILE:-/opt/stack/analytics-tables.txt}"

ident='^[A-Za-z0-9_]+$'
for value in "$MYSQL_DATABASE" "$ANALYTICS_DB_USER"; do
    [[ "$value" =~ $ident ]] || { echo "invalid identifier: $value" >&2; exit 1; }
done
# gen-env.sh writes hex; anything else could break the SQL string or the DuckDB ATTACH string.
[[ "$ANALYTICS_DB_PASSWORD" =~ ^[A-Za-z0-9_.-]+$ ]] \
    || { echo "ANALYTICS_DB_PASSWORD may only contain letters, digits, '_', '.' and '-'" >&2; exit 1; }
password="$ANALYTICS_DB_PASSWORD"
account="'${ANALYTICS_DB_USER}'@'%'"

sql="CREATE USER IF NOT EXISTS ${account} IDENTIFIED BY '${password}';
ALTER USER ${account} IDENTIFIED BY '${password}';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM ${account};
"
count=0
while read -r table columns _ || [ -n "${table:-}" ]; do
    case "${table:-#}" in \#*) continue ;; esac
    [[ "$table" =~ ^mdl_[a-z0-9_]+$ ]] || { echo "invalid table name: $table" >&2; exit 1; }
    [[ "${columns:-}" =~ ^[a-z0-9_]+(,[a-z0-9_]+)*$ ]] || { echo "invalid column list for $table" >&2; exit 1; }
    sql+="GRANT SELECT (${columns}) ON \`${MYSQL_DATABASE}\`.\`${table}\` TO ${account};
"
    count=$((count + 1))
done < "$TABLES_FILE"
[ "$count" -gt 0 ] || { echo "no tables in $TABLES_FILE" >&2; exit 1; }

echo "Granting column-level SELECT on ${count} tables to ${ANALYTICS_DB_USER}"
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -h "$MYSQL_HOST" -uroot --connect-timeout=10 <<<"$sql"
