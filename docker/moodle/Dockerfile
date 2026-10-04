FROM composer:2.10.3 AS composer

# moodlehq/moodle-php-apache:8.3-bookworm, multi-arch index digest recorded 2026-10-04.
# Refresh: docker buildx imagetools inspect moodlehq/moodle-php-apache:8.3-bookworm
FROM moodlehq/moodle-php-apache:8.3-bookworm@sha256:501f19fa75ad3cdc8962f2a742f39d179b8aa8ffdc2ff233d8d27a32f14e0e05

ARG MOODLE_VERSION=v5.3.0

COPY --from=composer /usr/bin/composer /usr/local/bin/composer

RUN command -v git >/dev/null || (apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*)

# Moodle 5.1+ loads some third-party libraries (e.g. league/oauth2-server) only from vendor/.
RUN cd / && rm -rf /var/www/html \
    && git clone --depth 1 --branch "${MOODLE_VERSION}" https://github.com/moodle/moodle.git /var/www/html \
    && rm -rf /var/www/html/.git \
    && if [ -d /var/www/html/public ]; then echo /var/www/html/public > /etc/moodle-dirroot; else echo /var/www/html > /etc/moodle-dirroot; fi \
    && if [ -f /var/www/html/composer.lock ] && [ -d /var/www/html/public ]; then \
        composer install --working-dir=/var/www/html --no-dev --no-interaction --no-progress --optimize-autoloader \
        && rm -rf /root/.composer /root/.cache/composer; \
    fi \
    && chown -R www-data:www-data /var/www/html

# Phase e adds plugin/local_askdata; it is installed only when present.
COPY plugin/ /tmp/plugin/
RUN if [ -d /tmp/plugin/local_askdata ]; then \
        cp -r /tmp/plugin/local_askdata "$(cat /etc/moodle-dirroot)/local/askdata" \
        && chown -R www-data:www-data "$(cat /etc/moodle-dirroot)/local/askdata"; \
    fi \
    && rm -rf /tmp/plugin

COPY docker/moodle/moodle-router.conf /etc/apache2/conf-enabled/moodle-router.conf
COPY docker/moodle/entrypoint.sh /usr/local/bin/moodle-stack-entrypoint
RUN chmod 0755 /usr/local/bin/moodle-stack-entrypoint

ENTRYPOINT ["moodle-stack-entrypoint"]
CMD ["apache2-foreground"]
