"""Health checks for managed agent configurations."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..agents.base import AgentAdapter
from .manager import resolve_config
from .state import StateStore, file_hash


@dataclass(frozen=True, slots=True)
class CheckResult:
    status: Literal["ok", "warning", "error", "drift"]
    agent: str
    check: str
    message: str


def check_agent(
    adapter: AgentAdapter,
    scope: Literal["global", "local"],
    repo_root: Path,
    scope_root: Path,
) -> list[CheckResult]:
    """Run schema, path, state, template, and optional binary checks."""
    results: list[CheckResult] = []
    merged, _ = resolve_config(adapter, scope, repo_root)
    errors = adapter.validate(merged.config)
    results.extend(
        CheckResult("error", adapter.name, "schema", error) for error in errors
    )
    if not errors:
        results.append(
            CheckResult("ok", adapter.name, "schema", "configuration is valid")
        )

    native = adapter.native_path(scope, repo_root)
    if native.exists():
        results.append(CheckResult("ok", adapter.name, "native", f"exists: {native}"))
    else:
        results.append(
            CheckResult("warning", adapter.name, "native", f"not found: {native}")
        )
    parent = native.parent
    writable_parent = next(
        (item for item in [parent, *parent.parents] if item.exists()), None
    )
    if writable_parent and os.access(writable_parent, os.W_OK):
        results.append(CheckResult("ok", adapter.name, "path", f"writable: {parent}"))
    else:
        results.append(
            CheckResult("error", adapter.name, "path", f"not writable: {parent}")
        )

    rendered = adapter.rendered_path(scope_root, scope)
    rendered_root = Path(scope_root) / adapter.name / "rendered"
    if (
        rendered.exists()
        and native.exists()
        and file_hash(rendered) != file_hash(native)
    ):
        results.append(
            CheckResult("drift", adapter.name, "drift", f"native differs: {native}")
        )
    elif rendered.exists() and not native.exists():
        results.append(
            CheckResult(
                "warning",
                adapter.name,
                "orphan",
                f"rendered but not synced: {rendered}",
            )
        )
    else:
        results.append(
            CheckResult("ok", adapter.name, "drift", "no rendered/native drift")
        )

    if rendered_root.exists():
        for candidate in rendered_root.rglob("*"):
            if candidate.is_file() and candidate != rendered:
                results.append(
                    CheckResult(
                        "warning",
                        adapter.name,
                        "orphan",
                        f"unexpected rendered file: {candidate}",
                    )
                )

    template_errors = adapter.template_errors()
    for error in template_errors:
        results.append(CheckResult("error", adapter.name, "template", error))
    if not template_errors:
        results.append(CheckResult("ok", adapter.name, "template", "templates compile"))

    if adapter.binary_name:
        if shutil.which(adapter.binary_name):
            results.append(
                CheckResult("ok", adapter.name, "binary", adapter.binary_name)
            )
        else:
            results.append(
                CheckResult(
                    "warning",
                    adapter.name,
                    "binary",
                    f"optional binary not found: {adapter.binary_name}",
                )
            )

    state = StateStore(scope_root)
    for stale in state.stale_entries():
        results.append(
            CheckResult("warning", adapter.name, "state", f"stale entry: {stale}")
        )
    return results
