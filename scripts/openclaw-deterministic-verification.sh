#!/bin/sh
set -u

repo="${PROPERTY_RENTAL_REPO:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
profile="${PROPERTY_RENTAL_VERIFICATION_PROFILE:-complete}"
evidence_file="${PROPERTY_RENTAL_VERIFICATION_EVIDENCE_FILE:-}"
passed=0
total=0
cd "$repo"

write_evidence() {
  result="$1"
  failed_gate="$2"
  failure_category="${3:-}"
  [ -n "$evidence_file" ] || return 0
  mkdir -p "$(dirname "$evidence_file")"
  temporary="$(mktemp "$(dirname "$evidence_file")/.verification.XXXXXX")"
  jq -cn \
    --arg profile "$profile" \
    --arg result "$result" \
    --arg failed_gate "$failed_gate" \
    --arg failure_category "$failure_category" \
    --argjson passed "$passed" \
    --argjson total "$total" \
    '{profile:$profile,result:$result,checks_passed:$passed,checks_observed:$total,failed_gate:(if $failed_gate == "" then null else $failed_gate end),failure_category:(if $failure_category == "" then null else $failure_category end)}' \
    >"$temporary"
  mv "$temporary" "$evidence_file"
}

run_gate() {
  gate="$1"
  shift
  total=$((total + 1))
  "$@"
  status=$?
  if [ "$status" -eq 0 ]; then
    passed=$((passed + 1))
    return 0
  fi
  category=deterministic_test_failure
  case "$status" in
    125|126|127) category=test_fixture_failure ;;
  esac
  write_evidence failed "$gate" "$category"
  return "$status"
}

if [ "$profile" = automation ]; then
  run_gate automation-test make automation-test || exit $?
  run_gate diff-check git diff --check || exit $?
  write_evidence passed ""
  exit 0
fi
[ "$profile" = complete ] || {
  total=1
  write_evidence failed unsupported-profile
  echo "Unsupported deterministic verification profile: $profile" >&2
  exit 64
}

# One stable foreground publication profile. The concise artifact stores stable
# gate IDs and observed counts, never raw logs, prompts, or secret values.
run_gate format-check make format-check || exit $?
run_gate lint make lint || exit $?
run_gate typecheck make typecheck || exit $?
run_gate build make build || exit $?
run_gate tests make test || exit $?
run_gate database-test make database-test || exit $?
run_gate automation-test make automation-test || exit $?
run_gate deployment-config make deployment-config-check || exit $?
run_gate frontend-audit make frontend-audit || exit $?
base="$(git merge-base HEAD '@{upstream}')"
run_gate traceability python3 scripts/traceability-audit.py --base "$base" || exit $?
run_gate state-json python3 -m json.tool ops/STATE.json || exit $?
run_gate roadmap-json python3 -m json.tool ops/V1_ROADMAP.json || exit $?
run_gate traceability-json python3 -m json.tool ops/traceability.json || exit $?
run_gate publication-guards "$repo/scripts/openclaw-publication-guard.sh" || exit $?
run_gate diff-check git diff --check || exit $?
write_evidence passed ""
