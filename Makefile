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

.PHONY: help install dev backend frontend test database-test migrate lint format format-check typecheck build \
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

lint: backend-lint frontend-lint

format: backend-format frontend-format

format-check: backend-format-check frontend-format-check

typecheck: backend-typecheck frontend-typecheck

build: backend-build backend-import-check frontend-build

backend-install:
	cd $(BACKEND_DIR) && $(UV) sync --extra dev

backend-dev:
	cd $(BACKEND_DIR) && $(UV) run uvicorn property_rental.app:app --reload --host 127.0.0.1 --port 8000

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
	./scripts/test-openclaw-routing.sh
