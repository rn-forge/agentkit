"""Inspect schemas, artifacts, templates, state, paths, and optional binaries.

The shared doctor command invokes :func:`check_agent` for each selected adapter
and reports warnings, errors, and native drift without mutating files.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..agents.base import AgentAdapter
from .manager import resolve_config
from .state import StateStore, content_hash, file_hash


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One diagnostic result emitted by an adapter health check."""

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
    """Run schema, path, state, template, binary, and artifact checks.

    Args:
        adapter: Adapter whose configuration and files are inspected.
        scope: Global or repository-local scope.
        repo_root: Repository root used for local native paths.
        scope_root: Agentkit working-data root containing state and staging.

    Returns:
        Ordered diagnostic results; callers decide which statuses affect exit.
    """
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

    rendered_root = Path(scope_root) / adapter.name / "rendered"
    expected_rendered: set[Path] = set()
    for artifact in adapter.artifacts(scope):
        native = adapter.native_path(scope, repo_root, artifact)
        if native.exists():
            results.append(
                CheckResult(
                    "ok", adapter.name, "native", f"{artifact.key} exists: {native}"
                )
            )
        else:
            results.append(
                CheckResult(
                    "warning",
                    adapter.name,
                    "native",
                    f"{artifact.key} not found: {native}",
                )
            )
        parent = native.parent
        writable_parent = next(
            (item for item in [parent, *parent.parents] if item.exists()), None
        )
        if writable_parent and os.access(writable_parent, os.W_OK):
            results.append(
                CheckResult("ok", adapter.name, "path", f"writable: {parent}")
            )
        else:
            results.append(
                CheckResult("error", adapter.name, "path", f"not writable: {parent}")
            )

        if artifact.root == "share":
            expected = adapter.render_artifact(artifact, merged.config, scope)
            differs = file_hash(native) != content_hash(expected)
            rendered = native
        else:
            rendered = adapter.rendered_path(scope_root, scope, artifact)
            expected_rendered.add(rendered)
            differs = (
                rendered.exists()
                and native.exists()
                and file_hash(rendered) != file_hash(native)
            )
        if differs:
            results.append(
                CheckResult(
                    "drift",
                    adapter.name,
                    "drift",
                    f"{artifact.key} differs: {native}",
                )
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
                CheckResult(
                    "ok", adapter.name, "drift", f"{artifact.key} has no drift"
                )
            )

    if rendered_root.exists():
        for candidate in rendered_root.rglob("*"):
            if candidate.is_file() and candidate not in expected_rendered:
                results.append(
                    CheckResult(
                        "warning",
                        adapter.name,
                        "orphan",
                        f"unexpected rendered file: {candidate}",
                    )
                )

    hooks_root = Path(scope_root) / "hooks"
    expected_share = _expected_share_paths(scope, repo_root)
    if hooks_root.exists():
        for candidate in hooks_root.rglob("*"):
            if candidate.is_file() and candidate not in expected_share:
                results.append(
                    CheckResult(
                        "warning",
                        adapter.name,
                        "orphan",
                        f"unexpected shared file: {candidate}",
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


def _expected_share_paths(
    scope: Literal["global", "local"], repo_root: Path
) -> set[Path]:
    from ..agents.registry import registry

    return {
        adapter.native_path(scope, repo_root, artifact)
        for adapter in registry.select(None)
        for artifact in adapter.artifacts(scope)
        if artifact.root == "share"
    }
