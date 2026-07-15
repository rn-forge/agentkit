#!/usr/bin/env bash
# agentkit: Claude prompt-secret guard adapter. Requires: jq

command -v jq &>/dev/null || { echo "BLOCKED [user-prompt-secret-guard]: jq not found — safety hook disabled. Install jq to proceed." >&2; exit 2; }

INPUT=$(cat)
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""')
. "$(dirname "$0")/../lib/guard-core.sh"

if REASON=$(guard_check_prompt_secrets "$PROMPT"); then
  exit 0
fi
echo "BLOCKED [user-prompt-secret-guard]: $REASON" >&2
exit 2
