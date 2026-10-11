#!/bin/sh
# Targeted PostgreSQL test run: the same throwaway container as
# scripts/database-test.sh, but pytest runs only the test paths given as
# arguments (backend-relative, for example tests/test_payment_return_migration.py
# or tests/test_payment_return_migration.py::test_name). The output never shows
# a database password or a database URL.
set -eu

if [ "$#" -eq 0 ]; then
  printf '%s\n' 'Usage: sh scripts/database-targeted-test.sh tests/test_x_migration.py [more test paths]' >&2
  exit 2
fi

for test_argument in "$@"; do
  test_file="${test_argument%%::*}"
  case "$test_file" in
    tests/test_*.py) ;;
    *)
      printf 'Only backend test paths under tests/ are accepted: %s\n' "$test_argument" >&2
      exit 2
      ;;
  esac
  case "$test_file" in
    *..*)
      printf 'Parent directory references are not accepted: %s\n' "$test_argument" >&2
      exit 2
      ;;
  esac
  if [ ! -f "backend/$test_file" ]; then
    printf 'Test file is missing: %s\n' "$test_file" >&2
    exit 2
  fi
done

project_name="prm-database-targeted-test-$$"
secret_directory="$(mktemp -d "${TMPDIR:-/tmp}/prm-database-targeted-test.XXXXXX")"
umask 077

cleanup() {
  docker compose --project-name "$project_name" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$secret_directory"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

redact_output() {
  awk '
    BEGIN {
      hex_run = "[0-9a-f]"
      for (hex_index = 1; hex_index < 16; hex_index++) {
        hex_run = hex_run "[0-9a-f]"
      }
      hex_run = hex_run "[0-9a-f]*"
      paths[1] = ENVIRON["POSTGRES_ADMIN_PASSWORD_FILE"]
      paths[2] = ENVIRON["POSTGRES_MIGRATION_PASSWORD_FILE"]
      paths[3] = ENVIRON["POSTGRES_RUNTIME_PASSWORD_FILE"]
      paths[4] = ENVIRON["POSTGRES_FINANCIAL_PASSWORD_FILE"]
      paths[5] = ENVIRON["POSTGRES_BACKUP_PASSWORD_FILE"]
      paths[6] = ENVIRON["POSTGRES_RESTORE_PASSWORD_FILE"]
      paths[7] = ENVIRON["POSTGRES_HUMAN_ADMIN_PASSWORD_FILE"]
      paths[8] = ENVIRON["POSTGRES_BOOTSTRAP_PASSWORD_FILE"]
      for (secret_index = 1; secret_index <= 8; secret_index++) {
        if ((getline value < paths[secret_index]) > 0 && value != "") {
          secrets[++secret_count] = value
        }
        close(paths[secret_index])
      }
    }
    {
      for (secret_index = 1; secret_index <= secret_count; secret_index++) {
        gsub(secrets[secret_index], "[REDACTED]")
      }
      gsub(/postgres(ql)?(\+[A-Za-z0-9_.-]+)?:\/\/[^ \t"'\'']*/, "[DATABASE URL REDACTED]")
      gsub(/[Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]=[^ \t"'\'']*/, "password=[REDACTED]")
      gsub(hex_run, "[HEX REDACTED]")
      print
    }
  '
}

POSTGRES_ADMIN_PASSWORD_FILE="$secret_directory/postgres_admin_password"
POSTGRES_MIGRATION_PASSWORD_FILE="$secret_directory/postgres_migration_password"
POSTGRES_RUNTIME_PASSWORD_FILE="$secret_directory/postgres_runtime_password"
POSTGRES_FINANCIAL_PASSWORD_FILE="$secret_directory/postgres_financial_password"
POSTGRES_BACKUP_PASSWORD_FILE="$secret_directory/postgres_backup_password"
POSTGRES_RESTORE_PASSWORD_FILE="$secret_directory/postgres_restore_password"
POSTGRES_HUMAN_ADMIN_PASSWORD_FILE="$secret_directory/postgres_human_admin_password"
POSTGRES_BOOTSTRAP_PASSWORD_FILE="$secret_directory/postgres_bootstrap_password"
POSTGRES_PORT=0

for secret_file in \
  "$POSTGRES_ADMIN_PASSWORD_FILE" \
  "$POSTGRES_MIGRATION_PASSWORD_FILE" \
  "$POSTGRES_RUNTIME_PASSWORD_FILE" \
  "$POSTGRES_FINANCIAL_PASSWORD_FILE" \
  "$POSTGRES_BACKUP_PASSWORD_FILE" \
  "$POSTGRES_RESTORE_PASSWORD_FILE" \
  "$POSTGRES_HUMAN_ADMIN_PASSWORD_FILE" \
  "$POSTGRES_BOOTSTRAP_PASSWORD_FILE"
do
  openssl rand -hex 32 >"$secret_file"
  chmod 0444 "$secret_file"
done

export POSTGRES_ADMIN_PASSWORD_FILE POSTGRES_MIGRATION_PASSWORD_FILE
export POSTGRES_RUNTIME_PASSWORD_FILE POSTGRES_BACKUP_PASSWORD_FILE
export POSTGRES_FINANCIAL_PASSWORD_FILE
export POSTGRES_RESTORE_PASSWORD_FILE POSTGRES_HUMAN_ADMIN_PASSWORD_FILE
export POSTGRES_BOOTSTRAP_PASSWORD_FILE
export POSTGRES_PORT

if docker compose --project-name "$project_name" up --detach --wait postgres \
  >/dev/null 2>"$secret_directory/compose_up.log"; then
  redact_output <"$secret_directory/compose_up.log" >&2
else
  startup_status=$?
  redact_output <"$secret_directory/compose_up.log" >&2 || true
  printf '%s\n' 'PostgreSQL container startup failed; redacted container logs follow' >&2
  docker compose --project-name "$project_name" logs --no-color postgres 2>&1 \
    | redact_output >&2 || true
  exit "$startup_status"
fi

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
FINANCIAL_DATABASE_URL="postgresql://prm_financial:$(cat "$POSTGRES_FINANCIAL_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
BACKUP_DATABASE_URL="postgresql://prm_backup:$(cat "$POSTGRES_BACKUP_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
RESTORE_DATABASE_URL="postgresql://prm_restore:$(cat "$POSTGRES_RESTORE_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
HUMAN_ADMIN_DATABASE_URL="postgresql://prm_human_admin:$(cat "$POSTGRES_HUMAN_ADMIN_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
BOOTSTRAP_DATABASE_URL="postgresql://prm_bootstrap:$(cat "$POSTGRES_BOOTSTRAP_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"

export TEST_ADMIN_DATABASE_URL
export MIGRATION_DATABASE_URL
export APP_DATABASE_URL
export FINANCIAL_DATABASE_URL
export BACKUP_DATABASE_URL
export RESTORE_DATABASE_URL
export HUMAN_ADMIN_DATABASE_URL
export BOOTSTRAP_DATABASE_URL

# Only the given test paths run: no caller pytest options or plugins.
unset PYTEST_ADDOPTS PYTEST_PLUGINS
cd backend
status_file="$secret_directory/pytest_status"
{
  if REQUIRE_DATABASE_TESTS=1 uv run --extra dev pytest --tb=short --no-header "$@" 2>&1; then
    printf '0\n' >"$status_file"
  else
    printf '%s\n' "$?" >"$status_file"
  fi
} | redact_output
pytest_status="$(cat "$status_file")"
exit "$pytest_status"
