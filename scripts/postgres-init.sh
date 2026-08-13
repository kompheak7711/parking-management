#!/bin/sh
set -eu

if [ "$POSTGRES_PASSWORD" = "$POSTGRES_MIGRATION_PASSWORD" ] || \
  [ "$POSTGRES_PASSWORD" = "$POSTGRES_RUNTIME_PASSWORD" ] || \
  [ "$POSTGRES_MIGRATION_PASSWORD" = "$POSTGRES_RUNTIME_PASSWORD" ]; then
  printf '%s\n' 'PostgreSQL bootstrap, migration, and runtime passwords must be distinct' >&2
  exit 1
fi

psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=migration_password="$POSTGRES_MIGRATION_PASSWORD" \
  --set=runtime_password="$POSTGRES_RUNTIME_PASSWORD" <<'SQL'
CREATE ROLE prm_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  PASSWORD :'migration_password';
CREATE ROLE prm_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  PASSWORD :'runtime_password';
ALTER DATABASE prm OWNER TO prm_migrator;
REVOKE ALL ON DATABASE prm FROM PUBLIC;
GRANT CONNECT ON DATABASE prm TO prm_runtime;
SQL