#!/usr/bin/env bash
# agentkit: shared PostToolUse hook — unwraps markdown prose (one line per
# paragraph/list item) after a Write/Edit/MultiEdit touches a .md file. Skips
# repos that opt out via a .nounwrap marker at the git repo root. Never
# blocks — always exits 0.

INPUT=$(cat)
FILE=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null || true)

[[ -z "$FILE" ]] && exit 0
case "$FILE" in *.md) ;; *) exit 0 ;; esac
[[ -f "$FILE" ]] || exit 0

DIR=$(dirname "$FILE")
REPO_ROOT=$(git -C "$DIR" rev-parse --show-toplevel 2>/dev/null || echo "$DIR")

[[ -f "$REPO_ROOT/.nounwrap" ]] && exit 0

python3 "${0%/*}/unwrap_md.py" "$FILE" 2>&1
exit 0
