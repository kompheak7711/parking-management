#!/bin/sh
# Catalog dump: apply every reviewed migration to a fresh throwaway PostgreSQL
# container, then print the current definition of each named function of the
# app schema (every overload, from pg_get_functiondef) in one read-only
# transaction. No test runs and nothing is written after the migrations. The
# output never shows a database password or a database URL.
#
# Usage: sh scripts/catalog-dump.sh <app function name> [<app function name> ...]
# A name holds only a-z, 0-9 and _ and is matched exactly (no pattern).
set -eu

if [ "$#" -eq 0 ]; then
  printf '%s\n' 'Usage: sh scripts/catalog-dump.sh <app function name> [<app function name> ...]' >&2
  exit 2
fi
for function_name in "$@"; do
  case "$function_name" in
    ''|*[!a-z0-9_]*)
      printf 'A function name may hold only a-z, 0-9 and _: %s\n' "$function_name" >&2
      exit 2
      ;;
  esac
done

project_name="prm-catalog-dump-$$"
secret_directory="$(mktemp -d "${TMPDIR:-/tmp}/prm-catalog-dump.XXXXXX")"
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

MIGRATION_DATABASE_URL="postgresql://prm_migrator:$(cat "$POSTGRES_MIGRATION_PASSWORD_FILE")@127.0.0.1:${published_port}/prm"
export MIGRATION_DATABASE_URL

cd backend
upgrade_log="$secret_directory/alembic_upgrade.log"
if uv run alembic upgrade head >"$upgrade_log" 2>&1; then
  upgrade_status=0
else
  upgrade_status=$?
fi
if [ "$upgrade_status" -ne 0 ]; then
  redact_output <"$upgrade_log" >&2
  printf 'Catalog dump FAILED: alembic upgrade head exited with status %s\n' "$upgrade_status" >&2
  exit "$upgrade_status"
fi
upgrade_count="$(grep -c 'Running upgrade' "$upgrade_log" || true)"

# The function names are passed as arguments and bound as query parameters;
# they are never placed into the SQL text.
dump_program='
import os
import sys

import psycopg

QUERY = """
SELECT procedure.oid::regprocedure::text, pg_catalog.pg_get_functiondef(procedure.oid)
FROM pg_catalog.pg_proc AS procedure
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
WHERE namespace.nspname = %s AND procedure.proname = %s AND procedure.prokind IN (%s, %s)
ORDER BY 1
"""

missing = []
with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as connection:
    connection.read_only = True
    with connection.cursor() as cursor:
        for name in sys.argv[1:]:
            cursor.execute(QUERY, ("app", name, "f", "p"))
            rows = cursor.fetchall()
            if not rows:
                missing.append(name)
            for signature, definition in rows:
                print(f"-- catalog-dump: {signature}")
                print(definition)
    connection.rollback()
for name in missing:
    print(f"No app function is named {name}", file=sys.stderr)
sys.exit(1 if missing else 0)
'

dump_output="$secret_directory/catalog_dump.txt"
if uv run python -I -c "$dump_program" "$@" >"$dump_output" 2>&1; then
  dump_status=0
else
  dump_status=$?
fi
redact_output <"$dump_output"
if [ "$dump_status" -ne 0 ]; then
  printf 'Catalog dump FAILED: the read exited with status %s\n' "$dump_status" >&2
  exit "$dump_status"
fi
printf 'Catalog dump done: %s upgrades applied on a fresh database\n' "$upgrade_count" >&2
