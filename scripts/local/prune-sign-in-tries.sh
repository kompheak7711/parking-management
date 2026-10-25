#!/bin/sh
# Removes wrong sign-in tries, their ended waits and the clears older than 30 days (V1-056 slice
# 12c; owner answer (a) to Q-2026-10-23-175), with the migration address read from
# .local/secrets into this process only. It prints only the three counts.
set -eu
. "$(dirname -- "$0")/common.sh"

file="$PRM_SECRETS/migration_database_url"
[ -s "$file" ] || prm_fail "Missing $file. Run: sh scripts/local/make-secrets.sh"
IFS= read -r MIGRATION_DATABASE_URL < "$file"
export MIGRATION_DATABASE_URL
cd "$PRM_ROOT/backend"
uv run python -m property_rental.sign_in_prune
