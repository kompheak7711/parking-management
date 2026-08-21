#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
script_dir="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
exec python3 "$script_dir/openclaw_automation.py" classify-state "$repo"
