#!/usr/bin/env bash
# agentkit: Claude destructive-command guard adapter. Requires: jq

command -v jq &>/dev/null || { echo "BLOCKED [pre-bash-guard]: jq not found — safety hook disabled. Install jq to proceed." >&2; exit 2; }

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""')
. "$(dirname "$0")/../lib/guard-core.sh"

if REASON=$(guard_check_bash_command "$CMD"); then
  exit 0
fi
echo "BLOCKED [pre-bash-guard]: $REASON. Requires explicit user confirmation." >&2
exit 2
