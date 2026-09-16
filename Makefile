.DEFAULT_GOAL := help
PYTHON ?= python
MESSAGE ?= What time is it?

.PHONY: help install infra-up infra-down infra-status worker run logs test fmt

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install dependencies (editable + dev)
	uv venv --python 3.12 .venv
	. .venv/bin/activate && uv pip install -e ".[dev]"

infra-up: ## Start local infrastructure (docker compose up -d) and wait for health
	$(PYTHON) -m app.entrypoints.infrastructure up

infra-down: ## Stop local infrastructure (docker compose down)
	$(PYTHON) -m app.entrypoints.infrastructure down

infra-status: ## Show health of each infrastructure service
	$(PYTHON) -m app.entrypoints.infrastructure status

worker: ## Run the Temporal worker
	$(PYTHON) -m app.entrypoints.worker

run: ## Execute the hello workflow: make run MESSAGE="What time is it?"
	$(PYTHON) -m app.entrypoints.workflow --message "$(MESSAGE)"

order: ## Run the multi-agent order pipeline: make order REQUEST="500 cases Pepsi, 20% off"
	$(PYTHON) -m app.entrypoints.order --request "$(REQUEST)"

logs: ## Tail infrastructure logs
	docker compose logs -f

test: ## Run unit tests
	$(PYTHON) -m pytest -q

services: ## Interactive start/stop/status for infra + worker
	./scripts/services.sh
