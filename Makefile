# ==================================================
# Property Rental Management
# Development Commands
# ==================================================

.DEFAULT_GOAL := help

UV ?= uv
BACKEND_DIR := backend
BACKEND_RUN := cd $(BACKEND_DIR) && $(UV) run --extra dev

.PHONY: help install dev backend test database-test migrate lint format format-check typecheck build \
	backend-install backend-dev backend-test backend-lint backend-format \
	backend-format-check backend-typecheck backend-build backend-import-check

help:
	@printf '%s\n' \
		"Property Rental Management" \
		"" \
		"Backend foundation commands:" \
		"  make install               Install locked backend development dependencies" \
		"  make dev                   Run the backend development server" \
		"  make test                  Run backend tests and traceability validation" \
		"  make database-test         Run real PostgreSQL migration tests (URLs required)" \
		"  make migrate               Apply reviewed migrations with MIGRATION_DATABASE_URL" \
		"  make lint                  Run Ruff lint checks" \
		"  make format-check          Check Ruff formatting without edits" \
		"  make format                Apply Ruff formatting" \
		"  make typecheck             Run strict mypy checks" \
		"  make build                 Build wheel/sdist and verify import" \
		"" \
		"Each command also has a backend-* target. Frontend/database targets are deferred."

install: backend-install

dev: backend-dev

backend: backend-dev

test: backend-test

database-test:
	./scripts/database-test.sh

migrate:
	cd $(BACKEND_DIR) && $(UV) run alembic upgrade head

lint: backend-lint

format: backend-format

format-check: backend-format-check

typecheck: backend-typecheck

build: backend-build backend-import-check

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
