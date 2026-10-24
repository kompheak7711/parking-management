#!/bin/sh
# Starts the API on the Mac mini for the local run (login sub-slice L7c; the L3c-1 binding:
# APP_ENVIRONMENT=production and the protected key file always passed).
#
#   sh scripts/local/start-api.sh
#
# sudo asks for your Mac password once: the installed helper opens the root-only key file and
# then runs the API as you, with the key on descriptor 4. The API listens on 127.0.0.1:8000
# only; the screens reach it through the HTTPS screen server (frontend, `npm run dev:local`).
# No password, key or database address is printed or passed as a command argument.
set -eu
. "$(dirname -- "$0")/common.sh"

if [ "${1:-}" != "--inner" ]; then
  [ -x "$PRM_HELPER" ] || prm_fail "Install the helper first (README, Local run on the Mac mini, step 2)."
  uv_path=$(command -v uv) || prm_fail "uv is not on your PATH."
  for name in runtime financial; do
    [ -s "$PRM_SECRETS/${name}_database_url" ] || prm_fail "Missing $PRM_SECRETS/${name}_database_url. Run: sh scripts/local/make-secrets.sh"
  done
  [ -s "$PRM_BLOCKLIST" ] || prm_fail "Missing $PRM_BLOCKLIST."
  origin=$(prm_origin)
  exec sudo "$PRM_HELPER" --key "$PRM_KEY_FILE" --fd 4 -- \
    /bin/sh "$PRM_ROOT/scripts/local/start-api.sh" --inner "$uv_path" "$origin"
fi

# Inner part: now running as you, with the key on descriptor 4.
uv_path=$2
origin=$3
[ "${PRM_PROTECTED_KEY_FD:-}" = 4 ] || prm_fail "Start it with: sh scripts/local/start-api.sh"
( : <&4 ) 2>/dev/null || prm_fail "Start it with: sh scripts/local/start-api.sh"
IFS= read -r APP_DATABASE_URL < "$PRM_SECRETS/runtime_database_url"
IFS= read -r APP_FINANCIAL_DATABASE_URL < "$PRM_SECRETS/financial_database_url"
APP_ENVIRONMENT=production
APP_TOTP_KEY_FILE=/dev/fd/4
APP_PASSWORD_BLOCKLIST_FILE=$PRM_BLOCKLIST
APP_ALLOWED_BROWSER_ORIGIN=$origin
export APP_DATABASE_URL APP_FINANCIAL_DATABASE_URL APP_ENVIRONMENT APP_TOTP_KEY_FILE
export APP_PASSWORD_BLOCKLIST_FILE APP_ALLOWED_BROWSER_ORIGIN
printf 'API for %s, on 127.0.0.1:8000. Stop it with Control-C.\n' "$APP_ALLOWED_BROWSER_ORIGIN"
cd "$PRM_ROOT/backend"
# The screen server adds X-Forwarded-For; it is trusted from 127.0.0.1 only, so each device on the
# Wi-Fi keeps its own sign-in waits and audit address, and none can claim another's.
exec "$uv_path" run uvicorn property_rental.app:app --host 127.0.0.1 --port 8000 --no-access-log \
  --proxy-headers --forwarded-allow-ips 127.0.0.1
