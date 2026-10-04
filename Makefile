SHELL := /bin/bash
COMPOSE := docker compose

.DEFAULT_GOAL := help

.PHONY: help env build up down logs clean init-model demo-data export sql ask test test-analytics smoke

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Create .env with random secrets if it does not exist
	@if [ ! -f .env ]; then ./scripts/gen-env.sh; else echo ".env already present"; fi

build: env ## Build the images
	$(COMPOSE) build

up: env ## Start the stack (installs Moodle on first run)
	$(COMPOSE) up -d --build

down: ## Stop the stack, keep volumes
	$(COMPOSE) down

logs: ## Follow logs of all services
	$(COMPOSE) logs -f

clean: ## Stop the stack and delete volumes
	$(COMPOSE) down -v

init-model: ## Pull the Ollama model
	@echo "init-model: not implemented yet (phase d)"; exit 1

demo-data: ## Generate demo courses and users
	./scripts/demo-data.sh

export: ## Export Moodle data to DuckDB now and print row counts
	$(COMPOSE) exec -T analytics python -m app.export

sql: ## Read-only query on the export, usage: make sql Q="SELECT ..."
	@test -n "$(Q)" || { echo 'usage: make sql Q="SELECT ..."'; exit 2; }
	@$(COMPOSE) exec -T analytics python -m app.sqlshell "$(Q)"

ask: ## Ask a question, usage: make ask Q="..."
	@echo "ask: not implemented yet (phase d)"; exit 1

test: test-analytics ## Run the test suite

test-analytics: ## Run the analytics unit and integration tests inside the container
	$(COMPOSE) exec -T analytics pytest -q

smoke: ## Run the end-to-end smoke test
	@echo "smoke: not implemented yet (phase f)"; exit 1
