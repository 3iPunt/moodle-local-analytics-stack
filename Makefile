SHELL := /bin/bash
COMPOSE := docker compose

.DEFAULT_GOAL := help

.PHONY: help env build up down logs clean init-model demo-data export ask test smoke

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Create .env with random secrets if it does not exist
	@if [ ! -f .env ]; then ./scripts/gen-env.sh; else echo ".env already present"; fi

build: env ## Build the Moodle image
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
	@echo "demo-data: not implemented yet (phase b)"; exit 1

export: ## Export Moodle data to DuckDB
	@echo "export: not implemented yet (phase c)"; exit 1

ask: ## Ask a question, usage: make ask Q="..."
	@echo "ask: not implemented yet (phase d)"; exit 1

test: ## Run the test suite
	@echo "test: not implemented yet (phase f)"; exit 1

smoke: ## Run the end-to-end smoke test
	@echo "smoke: not implemented yet (phase f)"; exit 1
