#!/usr/bin/env bash
# .claude/hooks/post-edit-format.sh  (PROJECT LEVEL)
# Runs after Write/Edit/MultiEdit. Set STACK below to enable formatting.
# Always exits 0 — never blocks Claude.

# ─── SET YOUR STACK ───────────────────────────────────────────────────────────
# Uncomment exactly one line (or leave blank to skip formatting):
#
# STACK=node       # npx prettier --write  (respects .prettierrc)
# STACK=python     # ruff format           (respects pyproject.toml)
# STACK=go         # gofmt -w
# STACK=shell      # shfmt -w
# STACK=java       # google-java-format --replace
# STACK=maven      # ./mvnw spotless:apply -q
# STACK=gradle     # ./gradlew spotlessApply -q
# ──────────────────────────────────────────────────────────────────────────────

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null || true)

[ -z "$FILE" ] && exit 0
[ ! -f "$FILE" ] && exit 0

case "${STACK:-}" in
  node) npx prettier --write "$FILE" 2>/dev/null || true ;;
  python) ruff format "$FILE" 2>/dev/null || true ;;
  go) gofmt -w "$FILE" 2>/dev/null || true ;;
  shell) shfmt -w "$FILE" 2>/dev/null || true ;;
  java) google-java-format --replace "$FILE" 2>/dev/null || true ;;
  maven) ./mvnw spotless:apply -q 2>/dev/null || true ;;
  gradle) ./gradlew spotlessApply -q 2>/dev/null || true ;;
  *) ;; # no formatter configured
esac

exit 0
