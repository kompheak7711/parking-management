#!/bin/sh
# Loads the design's sample data (mock-up v81) into the Mac mini's EMPTY test database, for the
# UI v81 screen checks (owner 08/11/2026):
#
#   sh scripts/local/seed-design-data.sh
#
# It refuses when the database already holds a Unit. The database address is read from
# .local/secrets into this process only. See scripts/local/seed-design-data.py for what it loads.
set -eu
. "$(dirname -- "$0")/common.sh"

file="$PRM_SECRETS/migration_database_url"
[ -s "$file" ] || prm_fail "Missing $file. Run: sh scripts/local/make-secrets.sh"
IFS= read -r MIGRATION_DATABASE_URL < "$file"
export MIGRATION_DATABASE_URL
cd "$PRM_ROOT/backend"
uv run python ../scripts/local/seed-design-data.py "$@"
