#!/usr/bin/env bash
# agentkit: Claude prompt-secret guard adapter. Requires: jq

LIB="${0%/*}/../../_common/hooks/guard-core.sh"
[[ -f "$LIB" ]] || { echo "BLOCKED [user-prompt-secret-guard]: guard library missing. Re-run agentkit global apply." >&2; exit 2; }
# shellcheck source=/dev/null
. "$LIB"

guard_require_jq_plain "user-prompt-secret-guard" warn

INPUT=$(cat)
# Deliberately advisory: a malformed prompt event enables no destructive action,
# so warn rather than block the user's turn. Command and write guards differ.
if ! guard_event_field "$INPUT" '.prompt'; then
  guard_emit_plain "user-prompt-secret-guard" "hook event was not valid JSON; prompt secret scan skipped." 1
fi
PROMPT="$GUARD_FIELD"

if REASON=$(guard_check_prompt_secrets "$PROMPT"); then
  exit 0
fi
guard_emit_plain "user-prompt-secret-guard" "$REASON" 2
