#!/bin/sh
set -eu

sha="${1:-}"
[ -n "$sha" ] || { echo "Usage: openclaw-wait-for-ci.sh <commit-sha>" >&2; exit 2; }
workflow_id="${PROPERTY_RENTAL_GITHUB_WORKFLOW_ID:-334806147}"
attempt=0
while [ "$attempt" -lt 120 ]; do
  result="$(gh api -X GET "repos/kompheak7711/property-rental-management/actions/workflows/$workflow_id/runs" \
    -f branch=implementation/foundation -f per_page=20 \
    --jq ".workflow_runs[] | select(.head_sha == \"$sha\") | [.status, (.conclusion // \"\")] | @tsv" \
    | head -1)"
  case "$result" in
    completed*success) exit 0 ;;
    completed*) echo "GitHub Actions failed for $sha: $result" >&2; exit 74 ;;
  esac
  attempt=$((attempt + 1))
  sleep 15
done
echo "Timed out waiting for GitHub Actions for $sha" >&2
exit 75
