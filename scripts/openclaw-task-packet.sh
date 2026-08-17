#!/bin/sh
set -eu

repo="${PROPERTY_RENTAL_REPO:-/Users/sokompheak/Development/property-rental-management}"
state_file="$repo/ops/STATE.json"

status="$(jq -r '.status // "unknown"' "$state_file")"
phase="$(jq -r '.next_candidate.phase // .phase // "unknown"' "$state_file")"
task="$(jq -r '.next_candidate.task // .task // .next_action // "unknown"' "$state_file")"
risk="$(jq -r '.next_candidate.risk_class // .execution.risk_class // "high"' "$state_file")"

case "$risk" in
  low|high) ;;
  *) risk=high ;;
esac

# A model-written low label is only a hint. Sensitive terms deterministically
# fail closed to Codex even when compact state is malformed or misclassified.
risk_text="$(printf '%s %s' "$phase" "$task" | tr '[:upper:]' '[:lower:]')"
case "$risk_text" in
  *auth*|*identity*|*permission*|*capabilit*|*secur*|*money*|*financ*|*account*|*bill*|*payment*|*deposit*|*lease*|*contract*|*tenant*|*customer*|*migration*|*schema*|*architect*|*production*|*deploy*|*credential*|*secret*|*canonical*|*business*policy*)
    risk=high
    ;;
esac

jq -cn \
  --arg status "$status" \
  --arg phase "$phase" \
  --arg task "$task" \
  --arg risk_class "$risk" \
  '{
    status: $status,
    phase: $phase,
    task: $task,
    risk_class: $risk_class,
    compact_inputs: ["ops/NOW.md", "ops/STATE.json", "ops/QUEUE.md"],
    prohibited: [
      "canonical_requirement_changes_without_separate_owner_authorization",
      "invented_business_or_financial_policy",
      "destructive_data_operations",
      "production_credentials_or_remote_access",
      "publication_with_failed_deterministic_or_github_actions_gates"
    ],
    report: ["outcome", "changed_paths", "verification", "blockers", "exact_next_candidate"]
  }'
