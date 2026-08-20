#!/bin/sh
set -eu

repo="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
PYTHONPATH="$repo/scripts${PYTHONPATH:+:$PYTHONPATH}" \
  python3 "$repo/scripts/test_openclaw_automation.py"

# Retain executable coverage for compact-state normalization and deterministic
# roadmap selection without invoking any model.
preflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
printf '%s' "$preflight" | jq -e '
  .actionable == false
  and .state_issue == "automation_repair_publication_required"
  and .status == "approved_ready"
  and .roadmap.current_id == "V1-018"
  and .roadmap.completed == 17
  and .roadmap.total == 60
' >/dev/null
packet="$(PROPERTY_RENTAL_AUTOMATION_STAGE=implementation PROPERTY_RENTAL_TEST_PROCESS_ROWS= "$repo/scripts/openclaw-task-packet.sh")"
printf '%s' "$packet" | jq -e '
  .schema_version == 2
  and .candidate == "V1-018"
  and .stage == "implementation"
  and .authorization_boundaries.standing_authorization == true
  and (.compact_inputs | length) == 4
  and (.output_contract.required | index("exact_next_action") != null)
' >/dev/null

if printf '%s' "$packet" | grep -q 'OPENCLAW_SUPERVISOR_PROMPT'; then
  echo "compact packet included the broad supervisor prompt" >&2
  exit 1
fi

echo "OpenClaw routing tests passed"
