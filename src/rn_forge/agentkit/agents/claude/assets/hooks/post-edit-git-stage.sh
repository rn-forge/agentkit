#!/usr/bin/env bash
# agentkit:claude hooks/post-edit-git-stage.sh
# Auto-stages edited/written files if inside a git repo.
# Keeps a running staged set without committing.
# Always exits 0 — never blocks.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // .tool_input.path // ""')

[ -z "$FILE" ] && exit 0
[ ! -f "$FILE" ] && exit 0

# Only act if inside a git repo
git rev-parse --is-inside-work-tree &>/dev/null || exit 0

# Stage the file
git add -- "$FILE" 2>/dev/null || true

exit 0
