#!/usr/bin/env bash
# agentkit: Codex prompt-secret guard adapter. Requires: jq

command -v jq >/dev/null 2>&1 || {
  printf '{"decision":"block","reason":"jq not found"}\n'
  exit 0
}

INPUT=$(cat)
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""')
. "$(dirname "$0")/../lib/guard-core.sh"

if REASON=$(guard_check_prompt_secrets "$PROMPT"); then
  exit 0
fi
jq -cn --arg reason "$REASON" '{decision:"block",reason:$reason}'
exit 0
