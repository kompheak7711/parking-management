#!/bin/sh
set -eu

project_name="prm-database-test-$$"

cleanup() {
  docker compose --project-name "$project_name" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

POSTGRES_ADMIN_PASSWORD="$(openssl rand -hex 32)"
POSTGRES_MIGRATION_PASSWORD="$(openssl rand -hex 32)"
POSTGRES_RUNTIME_PASSWORD="$(openssl rand -hex 32)"
POSTGRES_PORT=0

export POSTGRES_ADMIN_PASSWORD
export POSTGRES_MIGRATION_PASSWORD
export POSTGRES_RUNTIME_PASSWORD
export POSTGRES_PORT

docker compose --project-name "$project_name" up --detach --wait postgres >/dev/null

published_address="$(docker compose --project-name "$project_name" port postgres 5432)"
published_port="${published_address##*:}"
case "$published_port" in
  ''|*[!0-9]*)
    printf '%s\n' 'Unable to resolve the PostgreSQL loopback port' >&2
    exit 1
    ;;
esac

TEST_ADMIN_DATABASE_URL="postgresql://prm_admin:${POSTGRES_ADMIN_PASSWORD}@127.0.0.1:${published_port}/prm"
MIGRATION_DATABASE_URL="postgresql://prm_migrator:${POSTGRES_MIGRATION_PASSWORD}@127.0.0.1:${published_port}/prm"
APP_DATABASE_URL="postgresql://prm_runtime:${POSTGRES_RUNTIME_PASSWORD}@127.0.0.1:${published_port}/prm"

export TEST_ADMIN_DATABASE_URL
export MIGRATION_DATABASE_URL
export APP_DATABASE_URL

cd backend
REQUIRE_DATABASE_TESTS=1 uv run --extra dev pytest --tb=short --no-header tests/test_migrations.py
