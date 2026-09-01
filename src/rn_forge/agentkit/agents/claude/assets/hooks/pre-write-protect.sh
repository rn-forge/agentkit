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
# Fail closed: an unparseable event must not be read as "no path".
if ! guard_event_field "$INPUT" '.tool_input.file_path // .tool_input.notebook_path // .tool_input.path'; then
  guard_emit_plain "pre-write-protect" "hook event was not valid JSON or the path field had an unexpected type; refusing to run unclassified." 2
fi
FILE="$GUARD_FIELD"

[[ -z "$FILE" ]] && exit 0

if REASON=$(guard_check_write_path "$FILE"); then
  exit 0
fi
guard_emit_plain "pre-write-protect" "Write to '$FILE' ($REASON). Requires explicit user confirmation." 2
