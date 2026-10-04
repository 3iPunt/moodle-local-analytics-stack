#!/usr/bin/env bash
# Creates .env from .env.example with random secrets. Use --force to overwrite.
set -euo pipefail

cd "$(dirname "$0")/.."

SECRET_KEYS="MOODLE_ADMIN_PASSWORD MYSQL_ROOT_PASSWORD MYSQL_PASSWORD ANALYTICS_DB_PASSWORD ANALYTICS_SALT ASKDATA_SHARED_SECRET"

if [ -f .env ] && [ "${1:-}" != "--force" ]; then
    echo ".env already exists, use --force to overwrite" >&2
    exit 1
fi

command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

while IFS= read -r line || [ -n "$line" ]; do
    key="${line%%=*}"
    if [ "$key" != "$line" ] && [[ " $SECRET_KEYS " == *" $key "* ]]; then
        line="$key=$(openssl rand -hex 24)"
    fi
    printf '%s\n' "$line" >> "$tmp"
done < .env.example

mv "$tmp" .env
chmod 600 .env
echo "Wrote .env with fresh secrets"
