# ==================================================
# Property Rental Management
# Development Commands
# ==================================================

.DEFAULT_GOAL := help

UV ?= uv
NPM ?= npm
BACKEND_DIR := backend
BACKEND_RUN := cd $(BACKEND_DIR) && $(UV) run --extra dev
FRONTEND_DIR := frontend
FRONTEND_RUN := cd $(FRONTEND_DIR) && $(NPM) run

.PHONY: help install dev backend frontend test database-test migrate prune-sign-in-tries deployment-config-check lint format format-check typecheck build \
	backend-install backend-dev backend-test backend-lint backend-format \
	backend-format-check backend-typecheck backend-build backend-import-check \
	frontend-install frontend-dev frontend-test frontend-lint frontend-format \
	frontend-format-check frontend-typecheck frontend-build frontend-audit automation-test

help:
	@printf '%s\n' \
		"Property Rental Management" \
		"" \
		"Foundation commands:" \
		"  make install               Install locked backend and frontend dependencies" \
		"  make dev                   Run the backend development server" \
		"  make frontend              Run the frontend development server" \
		"  make test                  Run backend and frontend tests" \
		"  make database-test         Run real PostgreSQL migration tests (URLs required)" \
		"  make migrate               Apply reviewed migrations with MIGRATION_DATABASE_URL" \
		"  make prune-sign-in-tries   Remove wrong sign-in tries older than 30 days" \
		"  make deployment-config-check Validate placeholder-only deployment source contracts" \
		"  make lint                  Run backend and frontend lint checks" \
		"  make format-check          Check backend and frontend formatting" \
		"  make format                Apply backend and frontend formatting" \
		"  make typecheck             Run backend and frontend strict typing" \
		"  make build                 Build backend and frontend artifacts" \
		"  make frontend-audit        Audit locked frontend dependencies" \
		"  make automation-test       Test model routing without real model calls"

install: backend-install frontend-install

dev: backend-dev

backend: backend-dev

frontend: frontend-dev

test: backend-test frontend-test

database-test:
	./scripts/database-test.sh

migrate:
	cd $(BACKEND_DIR) && $(UV) run alembic upgrade head

prune-sign-in-tries:
	cd $(BACKEND_DIR) && $(UV) run python -m property_rental.sign_in_prune

deployment-config-check:
	python3 scripts/validate-deployment-config.py check-examples

lint: backend-lint frontend-lint

format: backend-format frontend-format

format-check: backend-format-check frontend-format-check

typecheck: backend-typecheck frontend-typecheck

build: backend-build backend-import-check frontend-build

backend-install:
	cd $(BACKEND_DIR) && $(UV) sync --extra dev

backend-dev:
	cd $(BACKEND_DIR) && $(UV) run uvicorn property_rental.app:app --reload --host 127.0.0.1 --port 8000 --no-access-log

backend-test:
	$(BACKEND_RUN) pytest

backend-lint:
	$(BACKEND_RUN) ruff check src tests

backend-format:
	$(BACKEND_RUN) ruff format src tests

backend-format-check:
	$(BACKEND_RUN) ruff format --check src tests

backend-typecheck:
	$(BACKEND_RUN) mypy

backend-build:
	$(BACKEND_RUN) python -m build

backend-import-check:
	$(BACKEND_RUN) python -c "from property_rental.app import app; assert app.title"

frontend-install:
	cd $(FRONTEND_DIR) && $(NPM) ci --ignore-scripts

frontend-dev:
	$(FRONTEND_RUN) dev

frontend-test:
	$(FRONTEND_RUN) test

frontend-lint:
	$(FRONTEND_RUN) lint

frontend-format:
	$(FRONTEND_RUN) format

frontend-format-check:
	$(FRONTEND_RUN) format:check

frontend-typecheck:
	$(FRONTEND_RUN) typecheck

frontend-build:
	$(FRONTEND_RUN) build

frontend-audit:
	cd $(FRONTEND_DIR) && $(NPM) audit --audit-level=moderate

automation-test:
	python3 scripts/validate-v1-roadmap.py
	python3 -m json.tool ops/AUTOMATION_TRACEABILITY.json >/dev/null
	./scripts/test-openclaw-routing.sh
	./scripts/test-openclaw-state-routing.sh
	./scripts/test-openclaw-visibility-watchdog.sh
	sh -n scripts/hermes-property-rental scripts/openclaw-deterministic-verification.sh \
		scripts/openclaw-hermes-task.sh scripts/openclaw-installation-check.sh \
		scripts/openclaw-publication-guard.sh scripts/openclaw-reconcile-published-state.sh \
		scripts/openclaw-select-next-candidate.sh scripts/openclaw-supervisor-dispatch.sh \
		scripts/openclaw-supervisor-preflight.sh scripts/openclaw-task-packet.sh \
		scripts/test-openclaw-routing.sh scripts/test-openclaw-state-routing.sh \
		scripts/test-openclaw-visibility-watchdog.sh
	python3 -c "from pathlib import Path; [compile(path.read_text(), str(path), 'exec') for path in Path('scripts').glob('openclaw*.py')]"
