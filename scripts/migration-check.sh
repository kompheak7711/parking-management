#!/bin/sh
# Migration-only check: apply every reviewed migration to a fresh throwaway
# PostgreSQL container and report the head revision. No test runs. The output
# never shows a database password or a database URL.
set -eu

project_name="pkm-migration-check-$$"
secret_directory="$(mktemp -d "${TMPDIR:-/tmp}/pkm-migration-check.XXXXXX")"
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

MIGRATION_DATABASE_URL="postgresql://prm_migrator:$(cat "$POSTGRES_MIGRATION_PASSWORD_FILE")@127.0.0.1:${published_port}/pkm"
export MIGRATION_DATABASE_URL

cd backend
status_file="$secret_directory/alembic_status"
upgrade_log="$secret_directory/alembic_upgrade.log"

{
  if uv run alembic upgrade head 2>&1; then
    printf '0\n' >"$status_file"
  else
    printf '%s\n' "$?" >"$status_file"
  fi
} | redact_output | tee "$upgrade_log"
upgrade_status="$(cat "$status_file")"
if [ "$upgrade_status" -ne 0 ]; then
  printf 'Migration check FAILED: alembic upgrade head exited with status %s\n' "$upgrade_status"
  exit "$upgrade_status"
fi

{
  if uv run alembic current 2>&1; then
    printf '0\n' >"$status_file"
  else
    printf '%s\n' "$?" >"$status_file"
  fi
} | redact_output
current_status="$(cat "$status_file")"
if [ "$current_status" -ne 0 ]; then
  printf 'Migration check FAILED: alembic current exited with status %s\n' "$current_status"
  exit "$current_status"
fi

upgrade_count="$(grep -c 'Running upgrade' "$upgrade_log" || true)"
printf 'Migration check passed: %s upgrades applied on a fresh database\n' "$upgrade_count"
