"""Inspect schemas, artifacts, templates, state, paths, and optional binaries.

The shared doctor command invokes :func:`check_agent` for each selected adapter
plus :func:`check_environment` once per scope, and reports warnings, errors, and
native drift without mutating files.

Every result carries a ``category`` so callers can group the report by concern
(``config``, ``artifacts``, ``environment``, ``state``) while ``check`` stays the
specific outcome. Each artifact contributes exactly one result — its worst
finding — rather than separate existence, path, and drift rows.
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

Status = Literal["ok", "warning", "error", "drift"]
Category = Literal["config", "artifacts", "environment", "state"]

CATEGORY_ORDER: tuple[Category, ...] = ("config", "artifacts", "environment", "state")
"""Display order for report sections."""

STATUS_ORDER: dict[Status, int] = {"error": 0, "drift": 1, "warning": 2, "ok": 3}
"""Display order within a section: most severe first."""


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One diagnostic result emitted by an adapter health check."""

    status: Status
    agent: str | None
    category: Category
    check: str
    message: str


def check_agent(
    adapter: AgentAdapter,
    scope: Literal["global", "local"],
    repo_root: Path,
    scope_root: Path,
) -> list[CheckResult]:
    """Run schema, template, binary, and per-artifact checks for one adapter.

    Agent-independent checks (hook dependencies, shared-file orphans, stale
    state) belong to the scope, not the adapter; see :func:`check_environment`.

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
        CheckResult("error", adapter.name, "config", "schema", error)
        for error in errors
    )
    if not errors:
        results.append(
            CheckResult(
                "ok", adapter.name, "config", "schema", "configuration is valid"
            )
        )

    template_errors = adapter.template_errors()
    results.extend(
        CheckResult("error", adapter.name, "config", "template", error)
        for error in template_errors
    )
    if not template_errors:
        results.append(
            CheckResult("ok", adapter.name, "config", "template", "templates compile")
        )

    rendered_root = Path(scope_root) / adapter.name / "rendered"
    expected_rendered: set[Path] = set()
    for artifact in adapter.artifacts(scope):
        native = adapter.native_path(scope, repo_root, artifact)
        native_exists = native.exists()

        if artifact.root == "share":
            rendered_exists = native_exists
            differs = native_exists and file_hash(native) != content_hash(
                adapter.render_artifact(artifact, merged.config, scope)
            )
        else:
            rendered = adapter.rendered_path(scope_root, scope, artifact)
            expected_rendered.add(rendered)
            rendered_exists = rendered.exists()
            differs = (
                rendered_exists
                and native_exists
                and file_hash(rendered) != file_hash(native)
            )

        results.append(
            _artifact_result(
                adapter.name,
                artifact.key,
                native,
                native_exists,
                rendered_exists,
                differs,
            )
        )

    if rendered_root.exists():
        for candidate in sorted(rendered_root.rglob("*")):
            if candidate.is_file() and candidate not in expected_rendered:
                results.append(
                    CheckResult(
                        "warning",
                        adapter.name,
                        "artifacts",
                        "orphan",
                        f"unexpected rendered file: {candidate}",
                    )
                )

    if adapter.binary_name:
        if shutil.which(adapter.binary_name):
            results.append(
                CheckResult(
                    "ok", adapter.name, "environment", "binary", adapter.binary_name
                )
            )
        else:
            results.append(
                CheckResult(
                    "warning",
                    adapter.name,
                    "environment",
                    "binary",
                    f"optional binary not found: {adapter.binary_name}",
                )
            )

    return results


def _artifact_result(
    agent: str,
    key: str,
    native: Path,
    native_exists: bool,
    rendered_exists: bool,
    differs: bool,
) -> CheckResult:
    """Collapse one artifact's path, existence, and drift findings into a row.

    Reports the most severe finding only: an unwritable parent directory blocks
    every later repair, drift matters more than absence, and a native file that
    was rendered but never synced is distinct from one that was never rendered.
    """
    parent = native.parent
    writable_parent = next(
        (item for item in [parent, *parent.parents] if item.exists()), None
    )
    if not (writable_parent and os.access(writable_parent, os.W_OK)):
        return CheckResult(
            "error", agent, "artifacts", "path", f"{key}: parent not writable: {parent}"
        )
    if differs:
        return CheckResult(
            "drift", agent, "artifacts", "drift", f"{key}: differs: {native}"
        )
    if not native_exists:
        if rendered_exists:
            return CheckResult(
                "warning",
                agent,
                "artifacts",
                "orphan",
                f"{key}: rendered but not synced: {native}",
            )
        return CheckResult(
            "warning", agent, "artifacts", "native", f"{key}: missing: {native}"
        )
    return CheckResult("ok", agent, "artifacts", "artifact", f"{key}: in sync")


def check_environment(
    scope: Literal["global", "local"],
    repo_root: Path,
    scope_root: Path,
) -> list[CheckResult]:
    """Run the checks that belong to the scope rather than to any one adapter.

    Hook dependencies, the shared hook directory, and the state store are shared
    across every adapter, so they are reported once instead of once per agent.

    Args:
        scope: Global or repository-local scope.
        repo_root: Repository root used for local native paths.
        scope_root: Agentkit working-data root containing state and staging.

    Returns:
        Ordered diagnostic results with no owning agent.
    """
    results: list[CheckResult] = []
    if shutil.which("jq"):
        results.append(CheckResult("ok", None, "environment", "dependency", "jq"))
    else:
        results.append(
            CheckResult(
                "error",
                None,
                "environment",
                "dependency",
                "required safety-hook dependency not found: jq",
            )
        )
    if shutil.which("gitleaks"):
        results.append(CheckResult("ok", None, "environment", "dependency", "gitleaks"))
    else:
        results.append(
            CheckResult(
                "warning",
                None,
                "environment",
                "dependency",
                "recommended secret-scanning dependency not found: gitleaks",
            )
        )

    hooks_root = Path(scope_root) / "hooks"
    expected_share = _expected_share_paths(scope, repo_root)
    if hooks_root.exists():
        for candidate in sorted(hooks_root.rglob("*")):
            if candidate.is_file() and candidate not in expected_share:
                results.append(
                    CheckResult(
                        "warning",
                        None,
                        "artifacts",
                        "orphan",
                        f"unexpected shared file: {candidate}",
                    )
                )

    state = StateStore(scope_root)
    for stale in state.stale_entries():
        results.append(
            CheckResult("warning", None, "state", "state", f"stale entry: {stale}")
        )
    return results


def sort_key(result: CheckResult) -> tuple[int, int, str, str]:
    """Order results most-severe first, then by agent and check within a status."""
    return (
        CATEGORY_ORDER.index(result.category),
        STATUS_ORDER[result.status],
        result.agent or "",
        result.check,
    )


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
