#!/usr/bin/env bash
# agentkit: Codex destructive-command guard adapter. Requires: jq

command -v jq >/dev/null 2>&1 || {
  printf '{"decision":"block","reason":"jq not found"}\n'
  exit 0
}

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""')
. "$(dirname "$0")/../lib/guard-core.sh"

if REASON=$(guard_check_bash_command "$CMD"); then
  exit 0
fi
jq -cn --arg reason "$REASON" '{decision:"block",reason:$reason}'
exit 0
