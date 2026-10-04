#!/usr/bin/env bash
# Configures Moodle for local_askdata. Runs inside the moodle container, idempotent:
#   docker compose exec -T moodle bash /opt/stack/scripts/configure-askdata.sh [--dry-run]
#
# - local_askdata/serviceurl   = ASKDATA_SERVICE_URL (default http://analytics:8000)
# - local_askdata/sharedsecret = ASKDATA_SHARED_SECRET
# - curlsecurityallowedport    = 443, 80 and the service port
# - curlsecurityblockedhosts   = Moodle's default list, except that the private range holding
#                                BACKEND_SUBNET is replaced by its exact complement, so only
#                                the backend network becomes reachable.
#
# set_config() works before the plugin is installed, so this can run first.
set -euo pipefail

if [ "$(id -u)" = 0 ]; then
    exec runuser -u www-data --preserve-environment -- bash "$0" "$@"
fi

php -- "$@" <<'PHP'
<?php
define('CLI_SCRIPT', true);
require('/var/www/html/config.php');
require_once($CFG->libdir . '/clilib.php');

$dryrun = in_array('--dry-run', $argv, true);
$subnet = getenv('BACKEND_SUBNET') ?: '172.28.0.0/24';
$serviceurl = getenv('ASKDATA_SERVICE_URL') ?: 'http://analytics:8000';
$secret = (string) getenv('ASKDATA_SHARED_SECRET');

// Moodle's default curlsecurityblockedhosts (admin/settings/security.php).
$defaults = ['127.0.0.0/8', '192.168.0.0/16', '10.0.0.0/8', '172.16.0.0/12', '0.0.0.0', 'localhost', '169.254.169.254', '0000::1'];

function parse_cidr(string $cidr): array {
    if (!preg_match('~^(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})$~', $cidr, $m) || ip2long($m[1]) === false || $m[2] > 32) {
        throw new invalid_argument_exception("invalid IPv4 CIDR: $cidr");
    }
    $prefix = (int) $m[2];
    $mask = $prefix === 0 ? 0 : (0xFFFFFFFF << (32 - $prefix)) & 0xFFFFFFFF;
    return [ip2long($m[1]) & $mask, $prefix];
}

function contains(array $outer, array $inner): bool {
    [$onet, $oprefix] = $outer;
    [$inet, $iprefix] = $inner;
    $mask = $oprefix === 0 ? 0 : (0xFFFFFFFF << (32 - $oprefix)) & 0xFFFFFFFF;
    return $iprefix >= $oprefix && ($inet & $mask) === $onet;
}

// CIDRs that cover $outer except $inner, smallest number of blocks, sorted by address.
function complement(array $outer, array $inner): array {
    [$inet, $iprefix] = $inner;
    $blocks = [];
    for ($p = $outer[1] + 1; $p <= $iprefix; $p++) {
        $mask = (0xFFFFFFFF << (32 - $p)) & 0xFFFFFFFF;
        $blocks[] = [($inet & $mask) ^ (1 << (32 - $p)), $p];
    }
    usort($blocks, fn($a, $b) => $a[0] <=> $b[0]);
    return array_map(fn($b) => long2ip($b[0]) . '/' . $b[1], $blocks);
}

$backend = parse_cidr($subnet);
$blocked = [];
$opened = false;
foreach ($defaults as $entry) {
    if (strpos($entry, '/') !== false && strpos($entry, ':') === false && contains(parse_cidr($entry), $backend)) {
        array_push($blocked, ...complement(parse_cidr($entry), $backend));
        $opened = true;
    } else {
        $blocked[] = $entry;
    }
}
if (!$opened) {
    cli_problem("BACKEND_SUBNET $subnet is not inside a blocked private range; the blocked list is left at Moodle's default.");
}

$port = parse_url($serviceurl, PHP_URL_PORT) ?: (parse_url($serviceurl, PHP_URL_SCHEME) === 'https' ? 443 : 80);
$ports = array_values(array_unique(['443', '80', (string) $port]));

if (!$dryrun && ($secret === '' || stripos($secret, 'changeme') !== false)) {
    cli_error('ASKDATA_SHARED_SECRET is empty or a placeholder; set it in .env');
}

$settings = [
    ['core', 'curlsecurityallowedport', implode("\n", $ports), false],
    ['core', 'curlsecurityblockedhosts', implode("\n", $blocked), false],
    ['local_askdata', 'serviceurl', $serviceurl, false],
    ['local_askdata', 'sharedsecret', $secret, true],
];

$show = fn(?string $v, bool $hidden) => $hidden ? ($v === null || $v === '' ? '(empty)' : '(hidden, ' . strlen($v) . ' chars)')
    : ($v === null ? '(unset)' : str_replace("\n", ', ', $v));

$changed = 0;
foreach ($settings as [$component, $name, $value, $hidden]) {
    $old = get_config($component, $name);
    $old = $old === false ? null : (string) $old;
    $label = $component === 'core' ? $name : "$component/$name";
    if ($old === $value) {
        cli_writeln("unchanged $label = " . $show($value, $hidden));
        continue;
    }
    cli_writeln(($dryrun ? 'would set ' : 'set       ') . "$label = " . $show($value, $hidden));
    cli_writeln("          (was " . $show($old, $hidden) . ")");
    if (!$dryrun) {
        set_config($name, $value, $component === 'core' ? null : $component);
        $changed++;
    }
}

if (!$dryrun) {
    purge_all_caches();
    cli_writeln("$changed setting(s) changed; caches purged.");
}
PHP
