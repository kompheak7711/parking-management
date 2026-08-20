#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
mode="${PROPERTY_RENTAL_GUARD_MODE:-worktree}"
cd "$repo"

case "$mode" in
  worktree|cached) ;;
  *)
    echo "Unsupported publication guard mode: $mode" >&2
    exit 64
    ;;
esac

# NUL-safe Python plumbing reads each actual worktree or index blob, including
# binary files. Candidate content is never echoed.
script_dir="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
python3 "$script_dir/openclaw_automation.py" publication-guard "$mode"

python3 -m json.tool ops/STATE.json >/dev/null
python3 -m json.tool ops/V1_ROADMAP.json >/dev/null
python3 -m json.tool ops/traceability.json >/dev/null
[ ! -f ops/AUTOMATION_TRACEABILITY.json ] || python3 -m json.tool ops/AUTOMATION_TRACEABILITY.json >/dev/null
if [ "$mode" = cached ]; then
  git diff --cached --check
else
  git diff --check
fi
