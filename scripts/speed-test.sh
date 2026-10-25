#!/bin/sh
set -eu

project_name="prm-speed-test-$$"
secret_directory="$(mktemp -d "${TMPDIR:-/tmp}/prm-speed-test.XXXXXX")"
umask 077

cleanup() {
  docker compose --project-name "$project_name" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$secret_directory"
}
trap cleanup EXIT HUP INT TERM

redact_container_logs() {
  awk '
    BEGIN {
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

if docker compose --project-name "$project_name" up --detach --wait postgres >/dev/null; then
  :
else
  startup_status=$?
  printf '%s\n' 'PostgreSQL container startup failed; redacted container logs follow' >&2
  docker compose --project-name "$project_name" logs --no-color postgres 2>&1 \
    | redact_container_logs >&2 || true
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

cd backend
# V1-060 speed test (DL-071 answer 14): made-up history, then the timed reads and Rent run.
# The made-up data lives only in this throwaway database, which is removed at the end.
uv run alembic upgrade head
uv run python speed/seed.py --units "${SPEED_UNITS:-300}" --years "${SPEED_YEARS:-10}"
uv run python speed/measure.py --report "${SPEED_REPORT:-../ops/reviews/V1-060-speed-test.md}"
