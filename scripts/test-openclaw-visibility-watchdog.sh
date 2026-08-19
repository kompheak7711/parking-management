#!/bin/sh
set -eu

source_repo="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT HUP INT TERM

repo="$test_root/repo"
ledger="$test_root/ledger"
database="$test_root/openclaw.sqlite"
mkdir -p "$repo/ops" "$repo/scripts" "$ledger"
cp "$source_repo/scripts/openclaw-visibility-watchdog.py" "$repo/scripts/"
cp "$source_repo/scripts/openclaw-supervisor-preflight.sh" "$repo/scripts/"
chmod +x "$repo/scripts/openclaw-supervisor-preflight.sh"

cat >"$repo/ops/STATE.json" <<'EOF'
{
  "phase": "Identity",
  "status": "published",
  "commit": "1234567890abcdef",
  "timestamp": "2026-08-18T00:00:00Z",
  "blockers": [],
  "roadmap": {"current_id": "V1-012", "total": 60},
  "next_candidate": {
    "id": "V1-013",
    "task": "MFA enrollment persistence foundation",
    "status": "approved_ready",
    "risk_class": "high"
  },
  "next_action": "Implement V1-013"
}
EOF
cat >"$repo/ops/V1_ROADMAP.json" <<'EOF'
{"total_tranches":60,"tranches":[{"id":"V1-001","status":"complete"},{"id":"V1-012","status":"complete"},{"id":"V1-013","status":"approved_ready"}]}
EOF
printf '%s\n' '# Test' >"$repo/ops/QUEUE.md"
git -C "$repo" init -q
git -C "$repo" add .
git -C "$repo" -c user.name=test -c user.email=test@example.invalid commit -qm test

sqlite3 "$database" <<'SQL'
CREATE TABLE cron_jobs (
  job_id TEXT PRIMARY KEY,
  enabled INTEGER,
  last_run_at_ms INTEGER,
  last_run_status TEXT,
  consecutive_errors INTEGER,
  running_at_ms INTEGER
);
INSERT INTO cron_jobs VALUES (
  '658ffdaf-1ac1-45a6-a842-f5f7d7a226eb', 1, 1787011200000, 'ok', 0, NULL
);
SQL

run_watchdog() {
  PROPERTY_RENTAL_REPO="$repo" \
  PROPERTY_RENTAL_OPENCLAW_DB="$database" \
  PROPERTY_RENTAL_WATCHDOG_STATE_DIR="$ledger" \
  PROPERTY_RENTAL_REPAIR_EXHAUSTED_DIR="$test_root/exhausted" \
  PROPERTY_RENTAL_NOW_MS=1787011200000 \
    python3 "$repo/scripts/openclaw-visibility-watchdog.py"
}

first="$(run_watchdog)"
printf '%s' "$first" | grep -q 'PHASE_COMPLETED — Property Rental Identity'
printf '%s' "$first" | grep -q 'published at 1234567'
printf '%s' "$first" | grep -q 'Roadmap progress: 2/60 complete; current V1-012'
printf '%s' "$first" | grep -q 'Next: Implement the approved bounded candidate: MFA enrollment persistence foundation'
[ -z "$(run_watchdog)" ]

jq '.status="unexpected_worker_state"
  | .approval={status:"unknown",implementation_started:false,implementation_completed:false,publication_completed:false}
  | .next_action=""
  | .next_candidate=null' \
  "$repo/ops/STATE.json" >"$repo/ops/STATE.json.new"
mv "$repo/ops/STATE.json.new" "$repo/ops/STATE.json"
contract_alert="$(run_watchdog)"
printf '%s' "$contract_alert" | grep -q 'STATE_CONTRACT_VIOLATION — Property Rental compact state'
[ -z "$(run_watchdog)" ]

echo "OpenClaw visibility watchdog tests passed"
