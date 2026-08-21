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
cp "$source_repo/scripts/openclaw_automation.py" "$repo/scripts/"
cp "$source_repo/scripts/openclaw-supervisor-preflight.sh" "$repo/scripts/"
cp "$source_repo/scripts/hermes-property-rental" "$repo/scripts/"
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
  name TEXT,
  enabled INTEGER,
  schedule_kind TEXT,
  every_ms INTEGER,
  payload_kind TEXT,
  payload_message TEXT,
  last_run_at_ms INTEGER,
  last_run_status TEXT,
  consecutive_errors INTEGER,
  running_at_ms INTEGER,
  updated_at INTEGER
);
INSERT INTO cron_jobs VALUES (
  '658ffdaf-1ac1-45a6-a842-f5f7d7a226eb',
  'property-rental-24x7-supervisor', 1, 'every', 1800000, 'command',
  '{"kind":"command","argv":["REPLACE_DISPATCHER"],"cwd":"REPLACE_REPO","noOutputTimeoutSeconds":10860,"outputMaxBytes":20000}',
  1787011200000, 'ok', 0, NULL, 1787011100000
);
SQL
sqlite3 "$database" "UPDATE cron_jobs SET payload_message=json_set(payload_message, '$.argv[0]', '$repo/scripts/openclaw-supervisor-dispatch.sh', '$.cwd', '$repo');"

run_watchdog() {
  PROPERTY_RENTAL_REPO="$repo" \
  PROPERTY_RENTAL_OPENCLAW_DB="$database" \
  PROPERTY_RENTAL_WATCHDOG_STATE_DIR="$ledger" \
  PROPERTY_RENTAL_INSTALLED_HERMES_WRAPPER="$repo/scripts/hermes-property-rental" \
  PROPERTY_RENTAL_REPAIR_EXHAUSTED_DIR="$test_root/exhausted" \
  PROPERTY_RENTAL_TEST_PROCESS_ROWS='' \
  PROPERTY_RENTAL_NOW_MS=1787011200000 \
    python3 "$repo/scripts/openclaw-visibility-watchdog.py"
}

first="$(run_watchdog)"
printf '%s' "$first" | grep -q 'PHASE_COMPLETED — Property Rental Identity'
printf '%s' "$first" | grep -q 'published at 1234567'
printf '%s' "$first" | grep -q 'Roadmap progress: 2/60 complete; current V1-012'
printf '%s' "$first" | grep -q 'Next: Implement the approved bounded candidate: MFA enrollment persistence foundation'
[ -z "$(run_watchdog)" ]
sqlite3 "$database" "UPDATE cron_jobs SET last_run_at_ms=1787011190000;"
[ -z "$(run_watchdog)" ]

sqlite3 "$database" "UPDATE cron_jobs SET every_ms=60000;"
malformed_alert="$(run_watchdog)"
printf '%s' "$malformed_alert" | grep -q 'SCHEDULER_UNHEALTHY'
sqlite3 "$database" "UPDATE cron_jobs SET every_ms=1800000;"
run_watchdog >/dev/null
sqlite3 "$database" "INSERT INTO cron_jobs SELECT 'duplicate-supervisor',name,enabled,schedule_kind,every_ms,payload_kind,payload_message,last_run_at_ms,last_run_status,consecutive_errors,running_at_ms,updated_at FROM cron_jobs WHERE job_id='658ffdaf-1ac1-45a6-a842-f5f7d7a226eb';"
duplicate_alert="$(run_watchdog)"
printf '%s' "$duplicate_alert" | grep -q 'SCHEDULER_UNHEALTHY'
sqlite3 "$database" "DELETE FROM cron_jobs WHERE job_id='duplicate-supervisor';"
run_watchdog >/dev/null

mkdir -p "$test_root/exhausted"
current_actionable="$(
  PYTHONPATH="$repo/scripts" \
  PROPERTY_RENTAL_REPO="$repo" \
  PROPERTY_RENTAL_TEST_PROCESS_ROWS='' \
    python3 - <<'PY'
import json, subprocess
from pathlib import Path
from openclaw_automation import stage_actionable_fingerprint
repo = Path(__import__('os').environ['PROPERTY_RENTAL_REPO'])
preflight = json.loads(subprocess.check_output([str(repo / 'scripts/openclaw-supervisor-preflight.sh')], cwd=repo, text=True))
print(stage_actionable_fingerprint(repo, preflight, candidate='V1-013', stage='idle'))
PY
)"
cat >"$test_root/exhausted/$current_actionable.json" <<'EOF'
{"status":"repair_exhausted","next_action":"Implement the approved bounded candidate: MFA enrollment persistence foundation","attempt_key":"exact-actionable-fingerprint","phase":"V1-013"}
EOF
exhausted_alert="$(run_watchdog)"
printf '%s' "$exhausted_alert" | grep -q 'REPAIR_EXHAUSTED — Property Rental automation stopped'
printf '%s' "$exhausted_alert" | grep -q 'Exact next action: Implement the approved bounded candidate'
[ -z "$(run_watchdog)" ]
rm "$test_root/exhausted/$current_actionable.json"

jq '.status="unexpected_worker_state"
  | .approval={status:"unknown",implementation_started:false,implementation_completed:false,publication_completed:false}
  | .next_action=""
  | .next_candidate=null' \
  "$repo/ops/STATE.json" >"$repo/ops/STATE.json.new"
mv "$repo/ops/STATE.json.new" "$repo/ops/STATE.json"
contract_alert="$(run_watchdog)"
printf '%s' "$contract_alert" | grep -q 'STATE_CONTRACT_VIOLATION — Property Rental compact state'
[ -z "$(run_watchdog)" ]

sqlite3 "$database" "UPDATE cron_jobs SET enabled=0, last_run_status='error', consecutive_errors=3, updated_at=1787011195000;"
disabled_alert="$(run_watchdog)"
printf '%s' "$disabled_alert" | grep -q 'SCHEDULER_DISABLED — Property Rental supervisor is intentionally disabled'
printf '%s' "$disabled_alert" | grep -q 'Owner action required: no'
if printf '%s' "$disabled_alert" | grep -q 'Investigation is required'; then
  echo 'intentionally disabled scheduler requested investigation' >&2
  exit 1
fi
[ -z "$(run_watchdog)" ]

sqlite3 "$database" "UPDATE cron_jobs SET enabled=1, last_run_at_ms=1787011190000, last_run_status='ok', consecutive_errors=0;"
pending_restoration_alert="$(run_watchdog)"
printf '%s' "$pending_restoration_alert" | grep -q 'SCHEDULER_UNHEALTHY — Property Rental scheduler is unhealthy'
[ -z "$(run_watchdog)" ]
sqlite3 "$database" "UPDATE cron_jobs SET last_run_at_ms=1787011200000;"
recovered_alert="$(run_watchdog)"
printf '%s' "$recovered_alert" | grep -q 'AUTOMATION_RECOVERED — Property Rental scheduler is healthy again'
[ -z "$(run_watchdog)" ]

sqlite3 "$database" "DELETE FROM cron_jobs;"
missing_alert="$(run_watchdog)"
printf '%s' "$missing_alert" | grep -q 'SCHEDULER_UNHEALTHY — Property Rental scheduler is unhealthy'
if printf '%s' "$missing_alert" | grep -q 'SCHEDULER_DISABLED'; then
  echo 'missing scheduler was misclassified as intentionally disabled' >&2
  exit 1
fi

echo "OpenClaw visibility watchdog tests passed"
