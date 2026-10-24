#!/bin/sh
# Starts (or, with "stop", stops) the local PostgreSQL service of compose.yaml with the password
# files of .local/secrets (login sub-slice L7c). It prints no password and no database address.
#
#   sh scripts/local/database.sh        # start and wait until it is ready
#   sh scripts/local/database.sh stop   # stop; the data stays in its Docker volume
set -eu
. "$(dirname -- "$0")/common.sh"

prm_export_password_files
cd "$PRM_ROOT"
case "${1:-start}" in
  start) docker compose up -d --wait postgres ;;
  stop) docker compose stop postgres ;;
  *) prm_fail "Use: sh scripts/local/database.sh [start|stop]" ;;
esac
