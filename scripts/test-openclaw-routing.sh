#!/bin/sh
set -eu

repo="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
PYTHONPATH="$repo/scripts${PYTHONPATH:+:$PYTHONPATH}" \
  python3 "$repo/scripts/test_openclaw_automation.py"

# Retain executable coverage for compact-state normalization and deterministic
# roadmap selection without coupling the test to one lifecycle stage.
preflight="$($repo/scripts/openclaw-supervisor-preflight.sh)"
expected_status="$(jq -r '.status' "$repo/ops/STATE.json")"
expected_candidate="$(jq -r '.next_candidate.roadmap_id // .next_candidate.id' "$repo/ops/STATE.json")"
expected_current="$(jq -r '.roadmap.current_id' "$repo/ops/STATE.json")"
expected_completed="$(jq '[.tranches[] | select(.status == "complete")] | length' "$repo/ops/V1_ROADMAP.json")"
expected_total="$(jq -r '.total_tranches' "$repo/ops/V1_ROADMAP.json")"
printf '%s' "$preflight" | jq -e '
  .status == $status
  and .roadmap.current_id == $current
  and .roadmap.completed == $completed
  and .roadmap.total == $total
  and (.actionable | type) == "boolean"
  and (.state_issue | type) == "string"
' --arg status "$expected_status" --arg current "$expected_current" \
  --argjson completed "$expected_completed" --argjson total "$expected_total" >/dev/null
packet="$(PROPERTY_RENTAL_AUTOMATION_STAGE=implementation PROPERTY_RENTAL_TEST_PROCESS_ROWS= "$repo/scripts/openclaw-task-packet.sh")"
printf '%s' "$packet" | jq -e '
  .schema_version == 2
  and .candidate == $candidate
  and .stage == "implementation"
  and (.authorization_boundaries.standing_authorization | type) == "boolean"
  and (.compact_inputs | length) == 4
  and (.output_contract.required | index("exact_next_action") != null)
' --arg candidate "$expected_candidate" >/dev/null

if printf '%s' "$packet" | grep -q 'OPENCLAW_SUPERVISOR_PROMPT'; then
  echo "compact packet included the broad supervisor prompt" >&2
  exit 1
fi

echo "OpenClaw routing tests passed"
