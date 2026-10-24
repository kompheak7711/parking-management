#!/bin/sh
# Makes the first Owner account on the Mac mini (login sub-slice L7c; SEC-073, API-100; the
# L7 runbook in README.md). Run it once, in Terminal, after the migrations:
#
#   sh scripts/local/bootstrap-owner.sh --username owner --display-name "CHETANA Owner" \
#     --audit-name chetana-owner
#
# sudo asks for your Mac password once: the installed helper opens the root-only key file and
# then runs the set-up as you. The set-up reads the database address (descriptor 3), the key
# (descriptor 4) and the password blocklist (descriptor 5) from files, never from arguments or
# the environment. It asks for the Owner password twice (nothing shows while you type), shows
# the sign-in key as letters and digits in this Terminal window only (type it in Google
# Authenticator with "Enter a setup key"), asks for the 6-digit code, shows the 10 recovery
# codes once, and asks you to type the acknowledgement. It prints nothing secret to a log, and
# it refuses to run when this window is not a terminal. From showing the key to the
# acknowledgement there are 15 minutes, enough to write the codes on paper.
set -eu
. "$(dirname -- "$0")/common.sh"

if [ "${1:-}" != "--inner" ]; then
  [ -t 0 ] && [ -t 1 ] || prm_fail "Run it in Terminal, not through a pipe or a file."
  for argument in "$@"; do
    case "$argument" in
      --database-url-fd*|--totp-key-fd*|--password-blocklist-fd*|--totp-key-identifier*|--ceremony-timeout-seconds*)
        prm_fail "$argument is set by this script." ;;
    esac
  done
  [ -x "$PRM_HELPER" ] || prm_fail "Install the helper first (README, Local run on the Mac mini, step 2)."
  uv_path=$(command -v uv) || prm_fail "uv is not on your PATH."
  [ -s "$PRM_SECRETS/bootstrap_database_url" ] || prm_fail "Missing $PRM_SECRETS/bootstrap_database_url. Run: sh scripts/local/make-secrets.sh"
  [ -s "$PRM_BLOCKLIST" ] || prm_fail "Missing $PRM_BLOCKLIST."
  exec sudo "$PRM_HELPER" --key "$PRM_KEY_FILE" --fd 4 -- \
    /bin/sh "$PRM_ROOT/scripts/local/bootstrap-owner.sh" --inner "$uv_path" "$@"
fi

# Inner part: now running as you, with the key on descriptor 4.
uv_path=$2
shift 2
[ "${PRM_PROTECTED_KEY_FD:-}" = 4 ] || prm_fail "Start it with: sh scripts/local/bootstrap-owner.sh"
( : <&4 ) 2>/dev/null || prm_fail "Start it with: sh scripts/local/bootstrap-owner.sh"
cd "$PRM_ROOT/backend"
exec "$uv_path" run python -m property_rental.bootstrap_cli "$@" \
  --totp-key-identifier local-mac-owner-bootstrap \
  --ceremony-timeout-seconds 900 \
  3< "$PRM_SECRETS/bootstrap_database_url" \
  5< "$PRM_BLOCKLIST"
