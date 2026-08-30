#!/usr/bin/env bash
# agentkit: Claude destructive-command guard adapter. Requires: jq

LIB="${0%/*}/../../_common/hooks/guard-core.sh"
[ -f "$LIB" ] || { echo "BLOCKED [pre-bash-guard]: guard library missing. Re-run agentkit global apply." >&2; exit 2; }
# shellcheck source=/dev/null
. "$LIB"

guard_require_jq_plain "pre-bash-guard" block

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""')

if REASON=$(guard_check_bash_command "$CMD"); then
  exit 0
fi
guard_emit_plain "pre-bash-guard" "$REASON. Requires explicit user confirmation." 2
