#!/usr/bin/env bash
# Runs once on first database initialisation (mysql image docker-entrypoint-initdb.d).
set -euo pipefail

: "${ANALYTICS_DB_USER:?ANALYTICS_DB_USER is required}"
: "${ANALYTICS_DB_PASSWORD:?ANALYTICS_DB_PASSWORD is required}"

echo "Creating read-only analytics user '${ANALYTICS_DB_USER}'"
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket -uroot <<EOSQL
CREATE USER IF NOT EXISTS '${ANALYTICS_DB_USER}'@'%' IDENTIFIED BY '${ANALYTICS_DB_PASSWORD}';
GRANT SELECT ON \`${MYSQL_DATABASE}\`.* TO '${ANALYTICS_DB_USER}'@'%';
EOSQL
