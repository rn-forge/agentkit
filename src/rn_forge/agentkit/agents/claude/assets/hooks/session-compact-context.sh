#!/usr/bin/env bash
# agentkit:claude hooks/session-compact-context.sh
# Fires via SessionStart/compact and PostCompact.
# Injects git state + reminders into context after compaction.

if ! command -v jq &>/dev/null; then
  echo "WARNING: jq not found — session-compact-context and safety hooks (pre-bash-guard, pre-write-protect) are disabled. Install jq immediately."
  exit 0
fi

INPUT=$(cat)
EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // ""' 2>/dev/null || true)
SOURCE=$(echo "$INPUT" | jq -r '.source // ""' 2>/dev/null || true)

# Fire on: session start after compaction, OR post-compaction within session
[ "$SOURCE" != "compact" ] && [ "$EVENT" != "PostCompact" ] && exit 0

# Git state
if git rev-parse --is-inside-work-tree &>/dev/null; then
  echo "## Git"
  echo "Branch: $(git branch --show-current 2>/dev/null)"
  git status --short 2>/dev/null || true
  echo ""
  echo "## Recent commits"
  git log --oneline -5 2>/dev/null || true
  echo ""
fi

exit 0
