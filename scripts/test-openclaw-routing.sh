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
expected_authorities="$(PYTHONPATH="$repo/scripts" python3 -c 'import json, sys; from pathlib import Path; from openclaw_automation import expand_authorities; roadmap = json.load(open(sys.argv[1], encoding="utf-8")); candidate = next(item for item in roadmap["tranches"] if item["id"] == sys.argv[2]); print(json.dumps(expand_authorities(candidate.get("authorities") or [], repo=Path(sys.argv[3])), separators=(",", ":")))' "$repo/ops/V1_ROADMAP.json" "$expected_candidate" "$repo")"
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
  .schema_version == 5
  and .candidate == $candidate
  and .stage == "implementation"
  and (.authorization_boundaries.existing_durable_v1 | type) == "boolean"
  and .authorization_boundaries.renewed_owner_authorization == false
  and (has("compact_inputs") | not)
  and (has("canonical_paths") | not)
  and (.requirement_evidence | map(.authority)) == $authorities
  and (.continuity_instructions | join(" ") | contains("no external skill lookup or compact-state reread"))
  and (.dispatcher_evidence_trust.instruction | contains("Do not spend tool calls rediscovering"))
  and (.output_contract.required | index("exact_next_action") != null)
' --arg candidate "$expected_candidate" --argjson authorities "$expected_authorities" >/dev/null

if printf '%s' "$packet" | grep -q 'OPENCLAW_SUPERVISOR_PROMPT'; then
  echo "compact packet included the broad supervisor prompt" >&2
  exit 1
fi

echo "OpenClaw routing tests passed"
