#!/bin/sh
# V1-059 backup and restore check (DL-071 answers 1 to 5): on a fresh throwaway PostgreSQL 17.6
# container with every reviewed migration, make two encrypted backups with the read-only backup
# identity, verify one, copy the newest to a pretend external drive, restore it into an empty
# throwaway database and compare every table, then show that a changed backup file is refused.
# The PostgreSQL client tools come from the same postgres:17.6 image (no host install needed).
# Nothing here touches a real database or real data. The output never shows a password, a key
# or a database URL.
set -eu

repository_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
project_name="prm-backup-check-$$"
work_directory="$(mktemp -d "${TMPDIR:-/tmp}/prm-backup-check.XXXXXX")"
umask 077

cleanup() {
  docker compose --project-directory "$repository_root" --project-name "$project_name" \
    down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$work_directory"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

secrets="$work_directory/secrets"
root="$work_directory/root"
tools="$work_directory/tools"
mkdir -p "$secrets" "$root" "$tools" "$root/drive"
: >"$root/drive/PRM-OFFHOST-DRIVE"

for name in admin migration runtime financial backup restore human_admin bootstrap; do
  file="$secrets/postgres_${name}_password"
  openssl rand -hex 32 >"$file"
  chmod 0444 "$file"
  upper="$(printf '%s' "$name" | tr 'a-z' 'A-Z')"
  export "POSTGRES_${upper}_PASSWORD_FILE=$file"
done
POSTGRES_PORT=0
export POSTGRES_PORT

compose() {
  docker compose --project-directory "$repository_root" --project-name "$project_name" "$@"
}

compose up --detach --wait postgres >/dev/null 2>"$work_directory/compose_up.log" || {
  printf '%s\n' 'PostgreSQL container startup failed' >&2
  exit 1
}
published_address="$(compose port postgres 5432)"
port="${published_address##*:}"
case "$port" in
  ''|*[!0-9]*) printf '%s\n' 'Unable to resolve the PostgreSQL loopback port' >&2; exit 1 ;;
esac

MIGRATION_DATABASE_URL="postgresql://prm_migrator:$(cat "$POSTGRES_MIGRATION_PASSWORD_FILE")@127.0.0.1:${port}/prm"
export MIGRATION_DATABASE_URL
if ! (cd "$repository_root/backend" && uv run alembic upgrade head >/dev/null 2>&1); then
  printf '%s\n' 'Backup check FAILED: the migrations did not apply' >&2
  exit 1
fi
unset MIGRATION_DATABASE_URL
printf '%s\n' 'Migrations applied on a fresh database'

compose exec -T postgres psql -q -U prm_admin -d prm -c 'CREATE DATABASE prm_restore_test' >/dev/null
printf 'postgresql://prm_backup:%s@127.0.0.1:%s/prm\n' \
  "$(cat "$POSTGRES_BACKUP_PASSWORD_FILE")" "$port" >"$secrets/backup_url"
printf 'postgresql://prm_admin:%s@127.0.0.1:%s/prm_restore_test\n' \
  "$(cat "$POSTGRES_ADMIN_PASSWORD_FILE")" "$port" >"$secrets/restore_url"
openssl rand -base64 32 >"$secrets/backup_key"
chmod 0600 "$secrets/backup_key" "$secrets/backup_url" "$secrets/restore_url"

for tool in pg_dump pg_restore; do
  cat >"$tools/$tool" <<EOF
#!/bin/sh
exec docker run --rm -i --network host --user "\$(id -u):\$(id -g)" \\
  -v "$root:$root" \\
  -e PGHOST -e PGPORT -e PGUSER -e PGDATABASE -e PGPASSFILE -e PGCONNECT_TIMEOUT -e PGAPPNAME \\
  postgres:17.6 $tool "\$@"
EOF
  chmod 0700 "$tools/$tool"
done

python3 - "$repository_root" "$work_directory" <<'PY'
import json, sys
repository, work = sys.argv[1], sys.argv[2]
with open(f"{repository}/config/deployment/production-operations.json", encoding="utf-8") as handle:
    config = json.load(handle)
config["backup"]["directory"] = f"{work}/root/backups"
config["backup"]["database_url_file"] = f"{work}/secrets/backup_url"
config["backup"]["encryption_key_file"] = f"{work}/secrets/backup_key"
config["status_directory"] = f"{work}/root/status"
with open(f"{work}/operations.json", "w", encoding="utf-8") as handle:
    json.dump(config, handle)
PY

backup() {
  (cd "$repository_root/backend" && uv run --quiet python -m property_rental.backup_job \
    --config "$work_directory/operations.json" --pg-bin "$tools" "$@")
}

backup run
sleep 1
backup run
first_backup="$(ls "$root/backups/hourly" | grep 'pgdump.enc$' | head -n 1)"
backup verify "$root/backups/hourly/$first_backup"
backup offhost-copy --kind daily --destination "$root/drive"
backup restore-test --target-database-url-file "$secrets/restore_url"

printf 'X' | dd of="$root/backups/hourly/$first_backup" bs=1 seek=200 conv=notrunc 2>/dev/null
if backup verify "$root/backups/hourly/$first_backup"; then
  printf '%s\n' 'Backup check FAILED: a changed backup file was accepted' >&2
  exit 1
fi
printf '%s\n' 'A changed backup file was refused, as it must be'
printf '%s\n' 'Backup check passed: backup, verify, off-host copy and restore test on PostgreSQL 17.6'
