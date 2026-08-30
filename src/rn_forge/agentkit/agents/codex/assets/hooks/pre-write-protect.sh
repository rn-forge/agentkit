#!/usr/bin/env bash
# agentkit: Codex sensitive-path write guard adapter. Requires: jq

LIB="${0%/*}/../../_common/hooks/guard-core.sh"
[ -f "$LIB" ] || { echo "BLOCKED [pre-write-protect]: guard library missing. Re-run agentkit global apply." >&2; exit 2; }
# shellcheck source=/dev/null
. "$LIB"

guard_require_jq_json "pre-write-protect" block

INPUT=$(cat)
FILE=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // .tool_input.path // ""')

if REASON=$(guard_check_write_path "$FILE"); then
  exit 0
fi
guard_emit_json_block "Write to '$FILE' ($REASON)"
