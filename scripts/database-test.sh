#!/bin/sh
set -eu

project_name="prm-database-test-$$"
secret_directory="$(mktemp -d "${TMPDIR:-/tmp}/prm-database-test.XXXXXX")"
umask 077

cleanup() {
  docker compose --project-name "$project_name" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$secret_directory"
}
trap cleanup EXIT HUP INT TERM

POSTGRES_ADMIN_PASSWORD_FILE="$secret_directory/postgres_admin_password"
POSTGRES_MIGRATION_PASSWORD_FILE="$secret_directory/postgres_migration_password"
POSTGRES_RUNTIME_PASSWORD_FILE="$secret_directory/postgres_runtime_password"
POSTGRES_BACKUP_PASSWORD_FILE="$secret_directory/postgres_backup_password"
POSTGRES_RESTORE_PASSWORD_FILE="$secret_directory/postgres_restore_password"
POSTGRES_HUMAN_ADMIN_PASSWORD_FILE="$secret_directory/postgres_human_admin_password"
POSTGRES_PORT=0

for secret_file in \
  "$POSTGRES_ADMIN_PASSWORD_FILE" \
  "$POSTGRES_MIGRATION_PASSWORD_FILE" \
  "$POSTGRES_RUNTIME_PASSWORD_FILE" \
  "$POSTGRES_BACKUP_PASSWORD_FILE" \
  "$POSTGRES_RESTORE_PASSWORD_FILE" \
  "$POSTGRES_HUMAN_ADMIN_PASSWORD_FILE"
do
  openssl rand -hex 32 >"$secret_file"
done

export POSTGRES_ADMIN_PASSWORD_FILE POSTGRES_MIGRATION_PASSWORD_FILE
export POSTGRES_RUNTIME_PASSWORD_FILE POSTGRES_BACKUP_PASSWORD_FILE
export POSTGRES_RESTORE_PASSWORD_FILE POSTGRES_HUMAN_ADMIN_PASSWORD_FILE
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

TEST_ADMIN_DATABASE_URL="postgresql://prm_admin:$(cat "$POSTGRES_ADMIN_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
MIGRATION_DATABASE_URL="postgresql://prm_migrator:$(cat "$POSTGRES_MIGRATION_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
APP_DATABASE_URL="postgresql://prm_runtime:$(cat "$POSTGRES_RUNTIME_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
BACKUP_DATABASE_URL="postgresql://prm_backup:$(cat "$POSTGRES_BACKUP_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
RESTORE_DATABASE_URL="postgresql://prm_restore:$(cat "$POSTGRES_RESTORE_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
HUMAN_ADMIN_DATABASE_URL="postgresql://prm_human_admin:$(cat "$POSTGRES_HUMAN_ADMIN_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"

export TEST_ADMIN_DATABASE_URL
export MIGRATION_DATABASE_URL
export APP_DATABASE_URL
export BACKUP_DATABASE_URL
export RESTORE_DATABASE_URL
export HUMAN_ADMIN_DATABASE_URL

cd backend
REQUIRE_DATABASE_TESTS=1 uv run --extra dev pytest --tb=short --no-header tests/test_migrations.py
