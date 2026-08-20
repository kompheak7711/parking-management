#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
stage="${PROPERTY_RENTAL_AUTOMATION_STAGE:-implementation}"
preflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
PYTHONPATH="$repo/scripts${PYTHONPATH:+:$PYTHONPATH}" python3 - "$repo" "$stage" "$preflight" <<'PY'
import json
import sys
from pathlib import Path

from openclaw_automation import task_packet

print(json.dumps(task_packet(Path(sys.argv[1]), json.loads(sys.argv[3]), sys.argv[2]), sort_keys=True))
PY
