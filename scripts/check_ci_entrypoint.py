"""Fail if a CI definition invokes a tool directly instead of `task`.

Handles both GitHub Actions (`run:`) and Azure Pipelines (`bash:`, `script:`,
`pwsh:`, `powershell:`) step syntax, including multi-line block scalars.

Usage: check_ci_entrypoint.py [repo-root]   (default: current directory)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Relative to the repo root. Keep only the providers this repo actually uses.
CI_DIRS = [".github/workflows"]

# The real tools the task vocabulary wraps — nobody, human or CI, should
# invoke these directly. Extend this list as new tools get wrapped.
FORBIDDEN_TOOLS = ["uv", "pytest", "ruff", "pyright", "mkdocs"]
STEP_KEYS = ("run", "bash", "script", "pwsh", "powershell")

# A step's command line — single-line `key: cmd` or the first line of a
# `key: |` block scalar. Matches the tool as the first token, or after a
# shell separator (&&, ||, ;, |), so `task setup && uv sync` is still caught
# even though `task` legitimately appears in the same line. The optional `./`
# is what catches wrapper scripts invoked by path — `./gradlew test`, `./mvnw`.
STEP_LINE = re.compile(r"^(\s*)(?:- )?(?:" + "|".join(STEP_KEYS) + r"):\s*(.*)$")
BLOCK_SCALAR = re.compile(r"^[|>][+-]?\d*$")
TOOL_INVOCATION = re.compile(r"(?:^|&&|\|\||;|\|)\s*(?:\./)?(" + "|".join(FORBIDDEN_TOOLS) + r")\b")


def check_command_line(label: Path, lineno: int, command: str) -> list[str]:
    return [
        f"{label}:{lineno}: step invokes `{m.group(1)}` directly — use `task` instead"
        for m in TOOL_INVOCATION.finditer(command)
    ]


def check_file(path: Path, label: Path) -> list[str]:
    errors: list[str] = []
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines):
        match = STEP_LINE.match(lines[i])
        if not match:
            i += 1
            continue
        indent, remainder = match.groups()
        if remainder and not BLOCK_SCALAR.match(remainder.strip()):
            errors.extend(check_command_line(label, i + 1, remainder))
            i += 1
            continue
        # Block scalar: consume subsequent, more-indented lines as the body.
        base_indent = len(indent)
        i += 1
        while i < len(lines):
            line = lines[i]
            if line.strip() and (len(line) - len(line.lstrip())) <= base_indent:
                break
            errors.extend(check_command_line(label, i + 1, line))
            i += 1

    return errors


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

    errors: list[str] = []
    for ci_dir in (root / d for d in CI_DIRS):
        if not ci_dir.exists():
            continue
        for path in sorted(ci_dir.rglob("*")):
            if path.is_file() and path.suffix in {".yml", ".yaml"}:
                errors.extend(check_file(path, path.relative_to(root)))

    if errors:
        for error in errors:
            print(error)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
