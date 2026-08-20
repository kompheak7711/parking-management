#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
exec python3 "$repo/scripts/openclaw_dispatch.py"
