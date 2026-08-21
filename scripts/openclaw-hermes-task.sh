#!/bin/sh
set -eu

task_file="${1:-}"
manifest_file="${2:-}"
[ "$#" -eq 2 ] && [ -f "$task_file" ] && [ -f "$manifest_file" ] || {
  echo "Usage: openclaw-hermes-task.sh <task-file> <invocation-manifest>" >&2
  exit 2
}

task="$(cat "$task_file")"
[ -n "$(printf '%s' "$task" | tr -d '[:space:]')" ] || {
  echo "ERROR: Hermes task file must not be empty or whitespace-only" >&2
  exit 2
}

repo="${PROPERTY_RENTAL_REPO:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
wrapper="${PROPERTY_RENTAL_HERMES_WRAPPER:-$repo/scripts/hermes-property-rental}"
exec "$wrapper" "$task_file" "$manifest_file"
