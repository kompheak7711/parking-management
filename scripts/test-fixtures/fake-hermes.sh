#!/bin/sh
set -eu
printf '%s\n' "$HERMES_MAX_ITERATIONS|$*" >"$FAKE_HERMES_CALL"
