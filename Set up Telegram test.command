#!/bin/sh
# Double-click in Finder to set up the Telegram bots for the test run, once
# (scripts/local/telegram-setup.sh).
cd "$(dirname -- "$0")" || exit 1
sh scripts/local/telegram-setup.sh
status=$?
printf '\nYou can close this window.\n'
exit "$status"
