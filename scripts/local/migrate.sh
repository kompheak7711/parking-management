#!/bin/sh
# Applies the reviewed migrations to the local database (login sub-slice L7c), as `make migrate`
# does, with the migration address read from .local/secrets into this process only.
set -eu
. "$(dirname -- "$0")/common.sh"

file="$PRM_SECRETS/migration_database_url"
[ -s "$file" ] || prm_fail "Missing $file. Run: sh scripts/local/make-secrets.sh"
IFS= read -r MIGRATION_DATABASE_URL < "$file"
export MIGRATION_DATABASE_URL
cd "$PRM_ROOT/backend"
uv run alembic upgrade head
