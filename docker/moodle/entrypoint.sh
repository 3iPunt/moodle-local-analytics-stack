#!/usr/bin/env bash
# Usage: moodle-stack-entrypoint [apache2-foreground | cron | <command>...]
set -Eeuo pipefail

# config.php, lib/setup.php and admin/cli/ stay at APP_ROOT in both layouts (5.1+ ships shims there).
# DIRROOT is the web root: APP_ROOT/public on 5.1+, APP_ROOT on older releases.
APP_ROOT=/var/www/html
DIRROOT="$(cat /etc/moodle-dirroot)"
DATAROOT=/var/www/moodledata
INSTALL_MARKER="$DATAROOT/.stack-install-complete"

: "${MOODLE_DB_HOST:=db}"
: "${MYSQL_DATABASE:?MYSQL_DATABASE is required}"
: "${MYSQL_USER:?MYSQL_USER is required}"
: "${MYSQL_PASSWORD:?MYSQL_PASSWORD is required}"
: "${MOODLE_WWWROOT:=http://localhost:8080}"
: "${MOODLE_SITE_NAME:=Moodle local stack}"
: "${MOODLE_ADMIN_EMAIL:=admin@example.com}"
: "${CRON_INTERVAL:=60}"

log() { echo "[moodle-stack] $*"; }

as_www() { runuser -u www-data -- "$@"; }

db_query() {
    php -r '
        mysqli_report(MYSQLI_REPORT_OFF);
        $db = @new mysqli(getenv("MOODLE_DB_HOST"), getenv("MYSQL_USER"), getenv("MYSQL_PASSWORD"), getenv("MYSQL_DATABASE"));
        if ($db->connect_errno) { exit(2); }
        if ($argv[1] === "") { exit(0); }
        $res = $db->query($argv[1]);
        if (!$res || !($row = $res->fetch_row())) { exit(1); }
        echo $row[0];
    ' -- "${1:-}"
}

wait_for_db() {
    log "Waiting for database at $MOODLE_DB_HOST"
    until db_query ""; do sleep 2; done
    log "Database is reachable"
}

is_installed() {
    db_query "SELECT value FROM mdl_config WHERE name = 'version'" >/dev/null 2>&1
}

write_config() {
    php -r '
        $cfg = [
            "dbtype" => "mysqli",
            "dblibrary" => "native",
            "dbhost" => getenv("MOODLE_DB_HOST"),
            "dbname" => getenv("MYSQL_DATABASE"),
            "dbuser" => getenv("MYSQL_USER"),
            "dbpass" => getenv("MYSQL_PASSWORD"),
            "prefix" => "mdl_",
            "wwwroot" => getenv("MOODLE_WWWROOT"),
            "dataroot" => "/var/www/moodledata",
            "admin" => "admin",
        ];
        $out = "<?php\nunset(\$CFG);\nglobal \$CFG;\n\$CFG = new stdClass();\n\n";
        foreach ($cfg as $k => $v) {
            $out .= "\$CFG->$k = " . var_export($v, true) . ";\n";
        }
        $out .= "\$CFG->dboptions = [\"dbpersist\" => 0, \"dbport\" => \"\", \"dbsocket\" => \"\", \"dbcollation\" => \"utf8mb4_unicode_ci\"];\n";
        $out .= "\$CFG->directorypermissions = 02777;\n";
        $out .= "\$CFG->routerconfigured = true;\n";
        $out .= "\$CFG->disableupdatenotifications = true;\n";
        $out .= "\$CFG->disableupdateautodeploy = true;\n";
        $out .= "\$CFG->phpunit_prefix = \"phpu_\";\n";
        $out .= "\$CFG->phpunit_dataroot = \"/var/www/phpunitdata\";\n\n";
        $out .= "require_once(__DIR__ . \"/lib/setup.php\");\n";
        file_put_contents("/var/www/html/config.php", $out);
    '
    chown root:www-data "$APP_ROOT/config.php"
    chmod 0640 "$APP_ROOT/config.php"
}

install_if_needed() {
    if is_installed; then
        log "Moodle is already installed, skipping installation"
    else
        : "${MOODLE_ADMIN_PASSWORD:?MOODLE_ADMIN_PASSWORD is required for installation}"
        log "Installing Moodle database"
        local start=$SECONDS
        as_www php "$APP_ROOT/admin/cli/install_database.php" \
            --agree-license \
            --adminuser=admin \
            --adminpass="$MOODLE_ADMIN_PASSWORD" \
            --adminemail="$MOODLE_ADMIN_EMAIL" \
            --fullname="$MOODLE_SITE_NAME" \
            --shortname=local \
            --lang=en
        log "Installation finished in $((SECONDS - start))s"
    fi
    as_www touch "$INSTALL_MARKER"
}

# Plugins bind-mounted from the host (local_askdata) may be newer than the database.
# upgrade.php exits 0 with "no upgrade needed" when nothing changed. A failed upgrade
# must not keep the whole site down, so it only warns; Moodle then shows the pending
# upgrade to administrators.
upgrade_if_needed() {
    log "Running upgrade.php (no-op when nothing changed)"
    local status=0
    as_www php "$APP_ROOT/admin/cli/upgrade.php" --non-interactive || status=$?
    if [ "$status" -ne 0 ]; then
        log "WARNING: upgrade.php failed with status $status. Moodle starts anyway, but the database may be"
        log "WARNING: older than the code. Fix the cause, then run: docker compose exec moodle runuser -u www-data -- php admin/cli/upgrade.php"
    fi
}

# Idempotent; a missing secret must not keep Moodle down, so failures only warn.
configure_askdata() {
    local script=/opt/stack/scripts/configure-askdata.sh
    [ -f "$script" ] || { log "No $script, skipping local_askdata configuration"; return 0; }
    log "Configuring local_askdata"
    bash "$script" || log "WARNING: configure-askdata.sh failed (status $?); the plugin will not reach the service"
}

run_cron() {
    log "Waiting for installation to complete"
    until [ -f "$INSTALL_MARKER" ] && is_installed; do sleep 5; done
    log "Starting cron loop every ${CRON_INTERVAL}s"
    while true; do
        as_www php "$APP_ROOT/admin/cli/cron.php" --keep-alive=0 || log "cron.php exited with status $?"
        log "Cron run completed at $(date -u +%FT%TZ)"
        sleep "$CRON_INTERVAL"
    done
}

chown www-data:www-data "$DATAROOT"
if [ -d /var/www/phpunitdata ]; then chown www-data:www-data /var/www/phpunitdata; fi
export APACHE_DOCUMENT_ROOT="$DIRROOT"

wait_for_db
write_config

case "${1:-}" in
    cron)
        run_cron
        ;;
    apache2-foreground)
        install_if_needed
        upgrade_if_needed
        configure_askdata
        exec moodle-docker-php-entrypoint "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
