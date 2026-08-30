#!/usr/bin/env bash
# agentkit: Claude prompt-secret guard adapter. Requires: jq

LIB="${0%/*}/../../_common/hooks/guard-core.sh"
[ -f "$LIB" ] || { echo "BLOCKED [user-prompt-secret-guard]: guard library missing. Re-run agentkit global apply." >&2; exit 2; }
# shellcheck source=/dev/null
. "$LIB"

guard_require_jq_plain "user-prompt-secret-guard" warn

INPUT=$(cat)
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""')

if REASON=$(guard_check_prompt_secrets "$PROMPT"); then
  exit 0
fi
guard_emit_plain "user-prompt-secret-guard" "$REASON" 2
