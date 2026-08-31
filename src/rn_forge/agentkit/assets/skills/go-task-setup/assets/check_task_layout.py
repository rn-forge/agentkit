"""Fail if the task vocabulary's wrapper/inner split has been violated.

Two rules, both structural — no per-stack configuration:

1. The root `Taskfile.yml` holds wrappers only. Every `cmds:` entry in it must
   be a `task:` call into a namespace file, never raw shell. Anything that
   shells out to a real tool belongs in the namespace file that owns it.
2. Every task, in the root file and in every `tasks/*.yml`, carries a non-empty
   `desc:`. That is what keeps `task --list` self-documenting, which is the
   whole reason the vocabulary is easier to remember than the tools underneath.

Usage: check_task_layout.py [repo-root]   (default: current directory)
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def task_specs(document: object) -> dict[str, object]:
    """The `tasks:` mapping of a Taskfile, or empty if there isn't one."""
    if not isinstance(document, dict):
        return {}
    tasks = document.get("tasks")
    return tasks if isinstance(tasks, dict) else {}


def check_desc(path: Path, name: str, spec: object) -> list[str]:
    if isinstance(spec, dict) and str(spec.get("desc", "")).strip():
        return []
    return [f"{path}: task `{name}` has no non-empty `desc:`"]


def check_wrapper_only(path: Path, name: str, spec: object) -> list[str]:
    """Every cmds entry in the root file must be a `task:` call."""
    # `name: echo hi` and `name: [a, b]` are go-task shorthand for raw shell.
    if isinstance(spec, (str, list)):
        return [f"{path}: task `{name}` is shorthand for a raw shell command — the root file holds wrappers only"]
    if not isinstance(spec, dict):
        return []

    errors: list[str] = []
    cmds = spec.get("cmds")
    if cmds is None:
        return errors
    if not isinstance(cmds, list):
        cmds = [cmds]

    for index, entry in enumerate(cmds):
        if isinstance(entry, dict) and "task" in entry:
            continue
        shown = entry if isinstance(entry, str) else type(entry).__name__
        errors.append(
            f"{path}: task `{name}` cmds[{index}] is not a `task:` call ({shown!r}) — "
            f"move the command into the namespace file that owns it and call it from here"
        )
    return errors


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    root_taskfile = root / "Taskfile.yml"

    if not root_taskfile.exists():
        print(f"{root_taskfile}: not found")
        return 1

    errors: list[str] = []

    document = yaml.safe_load(root_taskfile.read_text())
    for name, spec in task_specs(document).items():
        rel = root_taskfile.relative_to(root)
        errors.extend(check_desc(rel, name, spec))
        errors.extend(check_wrapper_only(rel, name, spec))

    for namespace_file in sorted((root / "tasks").glob("*.yml")):
        rel = namespace_file.relative_to(root)
        for name, spec in task_specs(yaml.safe_load(namespace_file.read_text())).items():
            errors.extend(check_desc(rel, name, spec))

    if errors:
        for error in errors:
            print(error)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
