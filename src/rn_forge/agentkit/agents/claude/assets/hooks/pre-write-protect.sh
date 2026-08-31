#!/usr/bin/env bash
# agentkit:claude hooks/pre-write-protect.sh
# Blocks writes/edits to sensitive files. Requires: jq
# Exit 2 = block. Exit 0 = allow.

LIB="${0%/*}/../../_common/hooks/guard-core.sh"
[[ -f "$LIB" ]] || { echo "BLOCKED [pre-write-protect]: guard library missing. Re-run agentkit global apply." >&2; exit 2; }
# shellcheck source=/dev/null
. "$LIB"

guard_require_jq_plain "pre-write-protect" block

INPUT=$(cat)
FILE=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // .tool_input.path // ""')

[[ -z "$FILE" ]] && exit 0

if REASON=$(guard_check_write_path "$FILE"); then
  exit 0
fi
guard_emit_plain "pre-write-protect" "Write to '$FILE' ($REASON). Requires explicit user confirmation." 2
