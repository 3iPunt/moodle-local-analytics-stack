<?php
// This file is part of Moodle - https://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// Moodle is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Moodle.  If not, see <https://www.gnu.org/licenses/>.

namespace local_askdata\local;

/**
 * Server-side HTTP client for the analytics service.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class client {
    /** @var int Connection timeout in seconds. */
    public const CONNECT_TIMEOUT = 5;

    /** @var int Maximum length of an error message coming from the service. */
    protected const MAX_MESSAGE_LENGTH = 300;

    /** @var array|null Canned response used by PHPUnit instead of a real HTTP call. */
    protected static ?array $testresponse = null;

    /** @var array|null Last request captured while a test response is set. */
    protected static ?array $lastrequest = null;

    /** @var \Closure|null Factory returning a \curl instance. */
    protected ?\Closure $curlfactory;

    /**
     * Constructor.
     *
     * @param string $serviceurl Base URL of the analytics service.
     * @param string $secret Shared HMAC secret.
     * @param int $timeout Request timeout in seconds.
     * @param int $maxrows Maximum number of rows to request and return.
     * @param callable|null $curlfactory Optional factory returning a \curl instance.
     */
    public function __construct(
        /** @var string Base URL of the analytics service. */
        protected string $serviceurl,
        /** @var string Shared HMAC secret. */
        protected string $secret,
        /** @var int Request timeout in seconds. */
        protected int $timeout = 60,
        /** @var int Maximum number of rows. */
        protected int $maxrows = 200,
        ?callable $curlfactory = null,
    ) {
        $this->curlfactory = $curlfactory === null ? null : \Closure::fromCallable($curlfactory);
    }

    /**
     * Builds a client from the plugin settings.
     *
     * @return self
     * @throws service_exception When the plugin is not configured.
     */
    public static function from_config(): self {
        $config = get_config('local_askdata');
        $url = trim((string) ($config->serviceurl ?? ''));
        $secret = (string) ($config->sharedsecret ?? '');
        if ($url === '' || $secret === '') {
            throw new service_exception('error_notconfigured', 'not_configured');
        }
        $timeout = (int) ($config->timeout ?? 60);
        $maxrows = (int) ($config->maxrows ?? 200);
        return new self($url, $secret, $timeout > 0 ? $timeout : 60, $maxrows > 0 ? $maxrows : 200);
    }

    /**
     * Sets a canned response for unit tests. Only honoured when PHPUNIT_TEST is defined.
     *
     * @param int|null $status HTTP status, or null to clear the canned response.
     * @param string $body Raw response body.
     * @param int $errno Simulated curl error number.
     */
    public static function set_test_response(?int $status, string $body = '', int $errno = 0): void {
        self::$lastrequest = null;
        self::$testresponse = $status === null ? null : ['status' => $status, 'body' => $body, 'errno' => $errno];
    }

    /**
     * Returns the last request captured while a canned response was set.
     *
     * @return array|null Keys: url, headers, body.
     */
    public static function get_last_test_request(): ?array {
        return self::$lastrequest;
    }

    /**
     * Returns the maximum number of rows this client returns.
     *
     * @return int
     */
    public function get_maxrows(): int {
        return $this->maxrows;
    }

    /**
     * Asks a question to the analytics service.
     *
     * @param string $question The natural-language question.
     * @param int[] $courseids Courses the answer may use.
     * @param int $userid The Moodle user asking, sent only as a pseudonymous HMAC.
     * @param int|null $now Unix timestamp to sign with, defaults to time().
     * @return array Keys: sql, columns, rows, elapsed_ms, truncated.
     * @throws service_exception On any transport, signature or service error.
     */
    public function ask(string $question, array $courseids, int $userid, ?int $now = null): array {
        $timestamp = $now ?? time();
        $body = json_encode([
            'question' => $question,
            'course_ids' => array_values(array_map('intval', $courseids)),
            'user_ref' => signer::user_ref($this->secret, $userid),
            'max_rows' => $this->maxrows,
        ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);

        $headers = [
            'Content-Type: application/json',
            'Accept: application/json',
            'X-Askdata-Timestamp: ' . $timestamp,
            'X-Askdata-Signature: ' . signer::sign($this->secret, $timestamp, $body),
        ];
        $url = rtrim($this->serviceurl, '/') . '/ask';

        $start = microtime(true);
        [$status, $raw, $errno] = $this->send($url, $headers, $body);
        $localelapsed = (int) round((microtime(true) - $start) * 1000);

        if ($errno !== 0 || $status === 0) {
            throw new service_exception('error_unreachable', 'unreachable', 0, null, 'curl errno ' . $errno);
        }

        $data = json_decode((string) $raw, true);

        if ($status < 200 || $status >= 300) {
            $this->throw_service_error($status, is_array($data) ? $data : null);
        }

        if (!is_array($data) || !array_key_exists('sql', $data) || !isset($data['columns'], $data['rows'])
                || !is_array($data['columns']) || !is_array($data['rows'])) {
            throw new service_exception('error_badresponse', 'bad_response', $status);
        }

        return $this->normalise($data, $localelapsed);
    }

    /**
     * Performs the HTTP POST.
     *
     * @param string $url Full endpoint URL.
     * @param string[] $headers Request headers.
     * @param string $body Raw JSON body.
     * @return array [int status, string body, int errno]
     */
    protected function send(string $url, array $headers, string $body): array {
        if (defined('PHPUNIT_TEST') && PHPUNIT_TEST && self::$testresponse !== null) {
            self::$lastrequest = ['url' => $url, 'headers' => $headers, 'body' => $body];
            return [self::$testresponse['status'], self::$testresponse['body'], self::$testresponse['errno']];
        }

        global $CFG;
        require_once($CFG->libdir . '/filelib.php');

        $curl = $this->curlfactory ? ($this->curlfactory)() : new \curl();
        $curl->setHeader($headers);
        $raw = $curl->post($url, $body, [
            'CURLOPT_TIMEOUT' => $this->timeout,
            'CURLOPT_CONNECTTIMEOUT' => self::CONNECT_TIMEOUT,
            'CURLOPT_FOLLOWLOCATION' => false,
        ]);
        $info = $curl->get_info();
        $status = is_array($info) ? (int) ($info['http_code'] ?? 0) : 0;
        return [$status, is_string($raw) ? $raw : '', (int) $curl->get_errno()];
    }

    /**
     * Converts an error response into a user-friendly exception.
     *
     * @param int $status HTTP status code.
     * @param array|null $data Decoded JSON body, if any.
     * @throws service_exception Always.
     */
    protected function throw_service_error(int $status, ?array $data): void {
        $reason = 'http_' . $status;
        $message = '';
        $detail = $data['detail'] ?? null;
        if (is_array($detail)) {
            if (isset($detail['reason']) && is_scalar($detail['reason'])) {
                $reason = (string) $detail['reason'];
            }
            if (isset($detail['message']) && is_scalar($detail['message'])) {
                $message = (string) $detail['message'];
            }
        } else if (is_string($detail)) {
            $message = $detail;
        }
        $reason = clean_param($reason, PARAM_ALPHANUMEXT);

        if ($status === 401 || $status === 403) {
            throw new service_exception('error_signature', $reason, $status);
        }

        $message = trim(clean_param($message, PARAM_TEXT));
        if ($message === '' || $status >= 500) {
            // Server errors may carry internal details, so they are not shown verbatim.
            throw new service_exception('error_service_generic', $reason, $status);
        }
        if (\core_text::strlen($message) > self::MAX_MESSAGE_LENGTH) {
            $message = \core_text::substr($message, 0, self::MAX_MESSAGE_LENGTH) . '...';
        }
        throw new service_exception('error_service', $reason, $status, $message);
    }

    /**
     * Normalises a successful response into the external function return structure.
     *
     * @param array $data Decoded response.
     * @param int $localelapsed Measured round trip in milliseconds, used when the service omits elapsed_ms.
     * @return array
     */
    protected function normalise(array $data, int $localelapsed): array {
        $columns = array_map([self::class, 'cell'], array_values($data['columns']));
        $rows = [];
        $truncated = !empty($data['truncated']);
        foreach (array_values($data['rows']) as $row) {
            if (count($rows) >= $this->maxrows) {
                $truncated = true;
                break;
            }
            $rows[] = array_map([self::class, 'cell'], is_array($row) ? array_values($row) : [$row]);
        }
        if (count($rows) >= $this->maxrows) {
            $truncated = true;
        }
        return [
            'sql' => is_scalar($data['sql']) ? (string) $data['sql'] : '',
            'columns' => $columns,
            'rows' => $rows,
            'elapsed_ms' => isset($data['elapsed_ms']) && is_numeric($data['elapsed_ms'])
                ? (int) $data['elapsed_ms'] : $localelapsed,
            'truncated' => $truncated,
        ];
    }

    /**
     * Casts a cell value to a string.
     *
     * @param mixed $value The value.
     * @return string
     */
    public static function cell($value): string {
        if ($value === null) {
            return '';
        }
        if (is_bool($value)) {
            return $value ? 'true' : 'false';
        }
        if (is_array($value) || is_object($value)) {
            return (string) json_encode($value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        }
        return (string) $value;
    }
}
