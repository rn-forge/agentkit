"""Inspect schemas, artifacts, templates, state, paths, and optional binaries.

The shared doctor command invokes :func:`check_agent` for each selected adapter plus
:func:`check_environment` once per scope, and reports every finding without mutating
files.

Each result separates three independent axes so no column repeats another:

``status``
    What is *true* of the thing checked — ``drift``, ``missing``, ``stale``, and so
    on. Naming the outcome here is what lets an artifact row drop a prose message
    entirely: ``source`` and ``target`` say which two files were compared, and
    ``status`` says how they differ.
``severity``
    How much that outcome matters, and the only thing exit codes read.
``kind``
    What sort of thing was checked — an artifact's :class:`~.artifacts.ArtifactKind`
    for managed files, or the check's own subject (``schema``, ``binary``,
    ``dependency``, …) for everything else.

``category`` remains as a grouping axis for callers that want it. Each artifact
contributes exactly one result — its worst finding — rather than separate existence,
path, and drift rows.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..agents.base import AgentAdapter
from ..agents.registry import registry
from .artifacts import Artifact, ArtifactKind
from .manager import resolve_config
from .state import StateStore, content_hash, file_hash

Status = Literal[
    "ok",
    "seeded",
    "drift",
    "stale",
    "missing",
    "unsynced",
    "orphan",
    "invalid",
    "unwritable",
]
"""The outcome of one check, independent of how much it matters.

``ok`` matches expectation; ``seeded`` is a user-owned file that exists and is
deliberately not compared; ``drift`` is a target whose content differs from its source;
``stale`` is a staged copy left behind by a source change; ``missing`` is an absent
target or unavailable dependency; ``unsynced`` is a rendered artifact that was never
copied to its target; ``orphan`` is a file agentkit no longer expects; ``invalid`` is
content that failed to validate or load; ``unwritable`` is a target whose parent
directory blocks every repair.
"""

Severity = Literal["info", "warning", "error"]
"""How much a status matters.

``error`` fails ``doctor``; nothing else does.
"""

Kind = Literal[
    ArtifactKind,
    "artifact",
    "schema",
    "template",
    "binary",
    "dependency",
    "state",
    "plugin",
]
"""What was checked: an artifact's own kind, or the subject of a scope-level check."""

Category = Literal["config", "artifacts", "environment", "state"]

CATEGORY_ORDER: tuple[Category, ...] = ("config", "artifacts", "environment", "state")
"""Display order for grouped output."""

SEVERITY_ORDER: dict[Severity, int] = {"error": 0, "warning": 1, "info": 2}
"""Display order within a group: most severe first."""

HEALTHY: frozenset[Status] = frozenset({"ok", "seeded"})
"""Statuses that represent a passing check."""

REPAIRABLE_BY_APPLY: frozenset[Status] = frozenset({"drift", "stale"})
"""Statuses ``--check`` treats as drift worth a distinct exit code."""

@dataclass(frozen=True, slots=True)
class CheckResult:
    """One diagnostic result emitted by an adapter or scope health check.

    Attributes:
        status: What is true of the thing checked.
        severity: How much that matters; only ``error`` fails the command.
        agent: Owning adapter, or ``None`` for a scope-level check.
        category: Grouping axis for report sections.
        kind: What sort of thing was checked.
        source: Packaged file the target is produced from, when the check
            compared two files.
        target: Native or staged file the check inspected.
        message: Detail that ``source``/``target`` cannot carry — a validation
            error, a dependency name, a plugin failure. Empty for artifact rows,
            whose status and two paths already say everything.
    """

    status: Status
    severity: Severity
    agent: str | None
    category: Category
    kind: Kind
    source: Path | None = None
    target: Path | None = None
    message: str = ""


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
        CheckResult("invalid", "error", adapter.name, "config", "schema", message=error)
        for error in errors
    )
    if not errors:
        results.append(CheckResult("ok", "info", adapter.name, "config", "schema"))

    template_errors = adapter.template_errors()
    results.extend(
        CheckResult(
            "invalid", "error", adapter.name, "config", "template", message=error
        )
        for error in template_errors
    )
    if not template_errors:
        results.append(CheckResult("ok", "info", adapter.name, "config", "template"))

    rendered_root = Path(scope_root) / adapter.name / "rendered"
    expected_rendered: set[Path] = set()
    for artifact in adapter.artifacts(scope):
        native = adapter.native_path(scope, repo_root, artifact)
        native_exists = native.exists()
        source = adapter.source_path(artifact)

        if artifact.seed_only:
            # Apply writes a seed file once and then never touches it again, so
            # its content belongs to the user. Only existence is a finding here;
            # comparing it against packaged content would report every ordinary
            # edit to AGENTS.md or CLAUDE.md as drift.
            if artifact.root != "share":
                expected_rendered.add(
                    adapter.rendered_path(scope_root, scope, artifact)
                )
            results.append(
                _seed_result(adapter.name, artifact, source, native, native_exists)
            )
            continue

        # Render the expected content once and compare *both* copies against it.
        # Comparing the staged copy with the native copy alone reports two
        # equally stale files as healthy whenever a template, a default, or a
        # packaged asset changed after the last apply.
        expected = content_hash(adapter.render_artifact(artifact, merged.config, scope))
        differs = native_exists and file_hash(native) != expected

        rendered: Path | None = None
        if artifact.root == "share":
            rendered_exists = native_exists
            stale = False
        else:
            rendered = adapter.rendered_path(scope_root, scope, artifact)
            expected_rendered.add(rendered)
            rendered_exists = rendered.exists()
            stale = rendered_exists and file_hash(rendered) != expected

        results.append(
            _artifact_result(
                adapter.name,
                artifact,
                source,
                native,
                native_exists,
                rendered,
                rendered_exists,
                differs,
                stale,
            )
        )

    if rendered_root.exists():
        for candidate in sorted(rendered_root.rglob("*")):
            if candidate.is_file() and candidate not in expected_rendered:
                results.append(
                    CheckResult(
                        "orphan",
                        "warning",
                        adapter.name,
                        "artifacts",
                        "artifact",
                        target=candidate,
                        message="unexpected rendered file",
                    )
                )

    if adapter.binary_name:
        found = shutil.which(adapter.binary_name)
        results.append(
            CheckResult(
                "ok" if found else "missing",
                "info" if found else "warning",
                adapter.name,
                "environment",
                "binary",
                message=adapter.binary_name,
            )
        )

    return results


def _seed_result(
    agent: str,
    artifact: Artifact,
    source: Path | None,
    native: Path,
    native_exists: bool,
) -> CheckResult:
    """Report a user-owned seed file by existence alone.

    Seed artifacts are written once and then owned by the user, so there is no expected
    content to compare against after the initial write — which is why the healthy status
    is ``seeded`` rather than ``ok``.
    """
    return CheckResult(
        "seeded" if native_exists else "missing",
        "info" if native_exists else "warning",
        agent,
        "artifacts",
        artifact.kind,
        source=source,
        target=native,
    )


def _artifact_result(
    agent: str,
    artifact: Artifact,
    source: Path | None,
    native: Path,
    native_exists: bool,
    rendered: Path | None,
    rendered_exists: bool,
    differs: bool,
    stale: bool = False,
) -> CheckResult:
    """Collapse one artifact's path, existence, and drift findings into a row.

    Reports the most severe finding only: an unwritable parent directory blocks
    every later repair, native drift matters more than stale staging, drift
    matters more than absence, and a native file that was rendered but never
    synced is distinct from one that was never rendered.
    """
    parent = native.parent
    writable_parent = next(
        (item for item in [parent, *parent.parents] if item.exists()), None
    )
    if not (writable_parent and os.access(writable_parent, os.W_OK)):
        return CheckResult(
            "unwritable",
            "error",
            agent,
            "artifacts",
            artifact.kind,
            source=source,
            target=native,
        )
    if differs:
        return CheckResult(
            "drift",
            "warning",
            agent,
            "artifacts",
            artifact.kind,
            source=source,
            target=native,
        )
    if stale:
        # The out-of-date file is the staged copy, not the native one, so point
        # `target` at what actually has to be rewritten.
        return CheckResult(
            "stale",
            "warning",
            agent,
            "artifacts",
            artifact.kind,
            source=source,
            target=rendered or native,
        )
    if not native_exists:
        return CheckResult(
            "unsynced" if rendered_exists else "missing",
            "warning",
            agent,
            "artifacts",
            artifact.kind,
            source=source,
            target=native,
        )
    return CheckResult(
        "ok", "info", agent, "artifacts", artifact.kind, source=source, target=native
    )


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
    # A plugin that failed to load is skipped rather than fatal (see
    # AgentRegistry.discover); doctor is where that becomes visible.
    results.extend(
        CheckResult(
            "invalid",
            "error",
            None,
            "environment",
            "plugin",
            message=(
                f"adapter entry point {error.entry_point!r} failed to load: "
                f"{error.reason}"
            ),
        )
        for error in registry.errors
    )
    dependencies: tuple[tuple[str, Severity, str], ...] = (
        ("jq", "error", "required by the safety hooks"),
        ("gitleaks", "warning", "recommended for secret scanning"),
    )
    for tool, severity, note in dependencies:
        found = shutil.which(tool)
        results.append(
            CheckResult(
                "ok" if found else "missing",
                "info" if found else severity,
                None,
                "environment",
                "dependency",
                message=tool if found else f"{tool} ({note})",
            )
        )

    hooks_root = Path(scope_root) / "hooks"
    expected_share = _expected_share_paths(scope, repo_root)
    if hooks_root.exists():
        for candidate in sorted(hooks_root.rglob("*")):
            if candidate.is_file() and candidate not in expected_share:
                results.append(
                    CheckResult(
                        "orphan",
                        "warning",
                        None,
                        "artifacts",
                        "artifact",
                        target=candidate,
                        message="unexpected shared file",
                    )
                )

    state = StateStore(scope_root)
    results.extend(
        CheckResult("stale", "warning", None, "state", "state", message=str(entry))
        for entry in state.stale_entries()
    )
    return results


def sort_key(result: CheckResult) -> tuple[int, int, str, str, str]:
    """Order results most-severe first, then by agent, kind, and target."""
    return (
        CATEGORY_ORDER.index(result.category),
        SEVERITY_ORDER[result.severity],
        result.agent or "",
        result.kind,
        str(result.target or result.message),
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
