#!/bin/sh
set -eu

POSTGRES_MIGRATION_PASSWORD="$(cat "${POSTGRES_MIGRATION_PASSWORD_FILE:?missing migration password file}")"
POSTGRES_RUNTIME_PASSWORD="$(cat "${POSTGRES_RUNTIME_PASSWORD_FILE:?missing runtime password file}")"
POSTGRES_BACKUP_PASSWORD="$(cat "${POSTGRES_BACKUP_PASSWORD_FILE:?missing backup password file}")"
POSTGRES_RESTORE_PASSWORD="$(cat "${POSTGRES_RESTORE_PASSWORD_FILE:?missing restore password file}")"
POSTGRES_HUMAN_ADMIN_PASSWORD="$(cat "${POSTGRES_HUMAN_ADMIN_PASSWORD_FILE:?missing human-admin password file}")"

export POSTGRES_MIGRATION_PASSWORD POSTGRES_RUNTIME_PASSWORD POSTGRES_BACKUP_PASSWORD
export POSTGRES_RESTORE_PASSWORD POSTGRES_HUMAN_ADMIN_PASSWORD

set -- "$POSTGRES_PASSWORD" "$POSTGRES_MIGRATION_PASSWORD" "$POSTGRES_RUNTIME_PASSWORD" \
  "$POSTGRES_BACKUP_PASSWORD" "$POSTGRES_RESTORE_PASSWORD" "$POSTGRES_HUMAN_ADMIN_PASSWORD"
for password do
  if [ -z "$password" ]; then
    printf '%s\n' 'PostgreSQL identity password files must be nonempty' >&2
    exit 1
  fi
done
while [ "$#" -gt 1 ]; do
  password="$1"
  shift
  for other_password do
    if [ "$password" = "$other_password" ]; then
      printf '%s\n' 'PostgreSQL identity passwords must be distinct' >&2
      exit 1
    fi
  done
done

psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv migration_password POSTGRES_MIGRATION_PASSWORD
\getenv runtime_password POSTGRES_RUNTIME_PASSWORD
\getenv backup_password POSTGRES_BACKUP_PASSWORD
\getenv restore_password POSTGRES_RESTORE_PASSWORD
\getenv human_admin_password POSTGRES_HUMAN_ADMIN_PASSWORD
CREATE ROLE prm_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  PASSWORD :'migration_password';
CREATE ROLE prm_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  PASSWORD :'runtime_password';
CREATE ROLE prm_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  PASSWORD :'backup_password';
CREATE ROLE prm_restore LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  PASSWORD :'restore_password';
CREATE ROLE prm_human_admin LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  PASSWORD :'human_admin_password';
ALTER DATABASE prm OWNER TO prm_migrator;
REVOKE ALL ON DATABASE prm FROM PUBLIC;
GRANT CONNECT ON DATABASE prm TO prm_runtime;
GRANT CONNECT ON DATABASE prm TO prm_backup;
GRANT CONNECT ON DATABASE prm TO prm_restore;
GRANT CONNECT ON DATABASE prm TO prm_human_admin;
GRANT pg_read_all_data TO prm_backup;
GRANT pg_monitor TO prm_human_admin;
SQL