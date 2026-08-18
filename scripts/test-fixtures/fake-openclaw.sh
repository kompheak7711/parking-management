#!/bin/sh
set -eu

model=""
session=""
message_file=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --model) model="$2"; shift 2 ;;
    --session-id) session="$2"; shift 2 ;;
    --message-file) message_file="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf '%s|%s\n' "$model" "$session" >>"$FAKE_CALLS"
grep -q 'openclaw-hermes-task.sh' "$message_file"
task_file="$(sed -n 's/.*openclaw-hermes-task.sh \([^`]*\)`.*/\1/p' "$message_file" | tail -1)"
[ -f "$task_file" ]
[ -n "$(tr -d '[:space:]' <"$task_file")" ]
case "$FAKE_SCENARIO:$model" in
  local_fail:ollama/*)
    printf '%s\n' '{"usage":{"total":1200}}'
    exit 1
    ;;
  local_stall:ollama/*)
    printf '%s\n' '{"usage":{"total":1300}}'
    exit 0
    ;;
  codex_stall:openai/*)
    printf '%s\n' '{"usage":{"total":1500}}'
    exit 0
    ;;
esac
case "$FAKE_SCENARIO:$model" in
  local_fail:openai/*|local_stall:openai/*)
    grep -q 'Execution route override: codex-escalation' "$message_file"
    grep -q 'PROPERTY_RENTAL_HERMES_ROUTE=codex' "$message_file"
    ;;
esac
jq '.status="published" | .next_action=""' "$PROPERTY_RENTAL_REPO/ops/STATE.json" >"$PROPERTY_RENTAL_REPO/ops/STATE.json.new"
mv "$PROPERTY_RENTAL_REPO/ops/STATE.json.new" "$PROPERTY_RENTAL_REPO/ops/STATE.json"
printf '%s\n' '{"usage":{"total":1400}}'
