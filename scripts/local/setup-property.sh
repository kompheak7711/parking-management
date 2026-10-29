#!/bin/sh
# Sets up the one Property on the Mac mini (V1-060), once, after the first Owner account:
#
#   sh scripts/local/setup-property.sh "CHETANA Parking"
#
# It makes the Property and its Owner, Manager and Staff bundles and gives the Owner the Owner
# bundle, so the screens find the Property by themselves. Running it again changes nothing.
# The database address is read from .local/secrets into this process only.
set -eu
. "$(dirname -- "$0")/common.sh"

[ $# -eq 1 ] && [ -n "$1" ] || prm_fail 'Give the Property name, for example: sh scripts/local/setup-property.sh "CHETANA Parking"'
file="$PRM_SECRETS/runtime_database_url"
[ -s "$file" ] || prm_fail "Missing $file. Run: sh scripts/local/make-secrets.sh"
IFS= read -r APP_DATABASE_URL < "$file"
export APP_DATABASE_URL
cd "$PRM_ROOT/backend"
uv run python -m property_rental.property_setup_cli --name "$1"
