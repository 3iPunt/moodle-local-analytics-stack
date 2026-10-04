SHELL := /bin/bash
# Ollama runtime profile: cpu (default) or gpu (NVIDIA, `make up OLLAMA_PROFILE=gpu`).
OLLAMA_PROFILE ?= cpu
COMPOSE := COMPOSE_PROFILES=$(OLLAMA_PROFILE) docker compose
# down/clean name every profile so no Ollama container is left behind.
COMPOSE_ALL := COMPOSE_PROFILES=cpu,gpu,init docker compose

.DEFAULT_GOAL := help

.PHONY: help env build up down logs clean init-model demo-data demo-reset export sql ask bench test test-analytics smoke

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Create .env with random secrets if it does not exist, refuse placeholder values
	@if [ ! -f .env ]; then ./scripts/gen-env.sh; else echo ".env already present"; fi
	@if awk '/^[A-Z_]+=.*changeme/ {found = 1} END {exit !found}' .env; then \
		echo "Refusing to continue: .env still contains 'changeme' placeholders:" >&2; \
		awk -F= '/^[A-Z_]+=.*changeme/ {print "  " $$1}' .env >&2; \
		echo "Run ./scripts/gen-env.sh --force or set real values." >&2; \
		exit 1; \
	fi

build: env ## Build the images
	$(COMPOSE) build

up: env ## Start the stack (installs Moodle on first run)
	$(COMPOSE) up -d --build

down: ## Stop the stack, keep volumes
	$(COMPOSE_ALL) down --remove-orphans

logs: ## Follow logs of all services
	$(COMPOSE) logs -f

clean: ## Stop the stack and delete volumes (including downloaded models)
	$(COMPOSE_ALL) down -v --remove-orphans

init-model: env ## Download OLLAMA_MODEL into the models volume (needs internet)
	docker compose --profile init run --rm model-init

demo-data: ## Generate demo courses and users, then export
	./scripts/demo-data.sh

# Named volumes of this project except ollama_models, so the model is not downloaded again.
DATA_VOLUMES := moodle-local-stack_db_data moodle-local-stack_moodledata moodle-local-stack_analytics_data

demo-reset: env ## DESTROYS Moodle, MySQL and export data, then reinstalls and regenerates the demo
	@echo "WARNING: demo-reset deletes this stack's Moodle site, database and export ($(DATA_VOLUMES))."
	@echo "The Ollama model volume is kept. Press Ctrl-C within 10 seconds to abort."
	@sleep 10
	$(COMPOSE_ALL) down --remove-orphans
	docker volume rm $(DATA_VOLUMES) 2>/dev/null || true
	$(COMPOSE) up -d --build
	@echo "Waiting for the analytics service to report healthy (Moodle installs first)"
	@for i in $$(seq 1 120); do \
		[ "$$(docker inspect -f '{{.State.Health.Status}}' moodle-local-stack-analytics-1 2>/dev/null)" = healthy ] && break; \
		sleep 5; \
	done; \
	[ "$$(docker inspect -f '{{.State.Health.Status}}' moodle-local-stack-analytics-1 2>/dev/null)" = healthy ] \
		|| { echo "analytics did not become healthy in 10 minutes" >&2; exit 1; }
	./scripts/demo-data.sh

export: ## Export Moodle data to DuckDB now and print row counts
	$(COMPOSE) exec -T analytics python -m app.export

sql: ## Read-only query on the export, usage: make sql Q="SELECT ..."
	@test -n "$(Q)" || { echo 'usage: make sql Q="SELECT ..."'; exit 2; }
	@$(COMPOSE) exec -T analytics python -m app.sqlshell "$(Q)"

ask: ## Ask a question, usage: make ask Q="..." [COURSES=2,3,4]
	@test -n "$(Q)" || { echo 'usage: make ask Q="..." [COURSES=2,3,4]'; exit 2; }
	@$(COMPOSE) exec -T analytics python -m app.cli ask "$(Q)" $(if $(COURSES),--course-ids $(COURSES))

bench: ## Run the six demo questions and write docs/benchmark.md
	$(COMPOSE) exec -T analytics python -m app.cli bench --markdown /tmp/benchmark.md
	$(COMPOSE) exec -T analytics cat /tmp/benchmark.md > docs/benchmark.md
	@echo "Wrote docs/benchmark.md"

test: test-analytics ## Run the test suite

# Integration tests export "as of" the demo generation time so the documented facts do not drift.
test-analytics: ## Run the analytics unit and integration tests inside the container
	@epoch="$$($(COMPOSE) exec -T moodle runuser -u www-data -- php /var/www/html/admin/cli/cfg.php \
		--component=local_stackdemo --name=variety_applied 2>/dev/null | tr -d '[:space:]')"; \
	echo "DEMO_NOW_EPOCH=$${epoch:-unset}"; \
	$(COMPOSE) exec -T -e DEMO_NOW_EPOCH="$$epoch" analytics pytest -q

smoke: ## Run the end-to-end smoke test
	@echo "smoke: not implemented yet (phase f)"; exit 1
