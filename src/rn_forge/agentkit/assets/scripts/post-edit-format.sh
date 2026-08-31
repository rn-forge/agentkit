#!/usr/bin/env bash
# agentkit: shared per-file post-edit formatter. Always exits 0 — never blocks.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null || true)

[[ -z "$FILE" ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

run_formatter() {
  local formatter="$1"
  shift
  if ! "$@"; then
    echo "WARNING [post-edit-format]: $formatter failed for '$FILE'." >&2
  fi
  return 0
}

case "$FILE" in
  *.py)
    command -v ruff >/dev/null 2>&1 && run_formatter ruff ruff format "$FILE"
    ;;
  *.ts | *.tsx | *.js | *.jsx | *.json | *.html | *.scss | *.css | *.md)
    command -v npx >/dev/null 2>&1 && run_formatter prettier npx prettier --write "$FILE"
    ;;
  *.java)
    command -v google-java-format >/dev/null 2>&1 && run_formatter google-java-format google-java-format --replace "$FILE"
    ;;
  *.sh)
    command -v shfmt >/dev/null 2>&1 && run_formatter shfmt shfmt -w "$FILE"
    ;;
  *) ;;
esac

exit 0
