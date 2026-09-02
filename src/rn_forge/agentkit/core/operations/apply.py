"""Resolve configuration and render or copy every artifact an adapter declares."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ...agents.base import AgentAdapter, Scope
from ..artifacts import Artifact
from ..config import MergeResult
from ..io import atomic_write, read_config
from ..paths import global_root, managed_config_path, project_scope_root, scope_root
from ..state import StateStore, backup_file, content_hash, file_hash
from .init import scaffold_managed_source
from .result import (
    OperationResult,
    content_diff,
    highest_source,
    managed_copy_path,
    mode_differs,
    seeded_result,
)


def artifact_drifted(
    artifact: Artifact,
    native_path: Path,
    rendered: Path,
    expected_hash: str,
) -> bool:
    """Report whether one artifact differs from what apply would write.

    A seed artifact is written once and then owned by the user — apply leaves it alone
    (see ``apply_resolved``) and diff skips it — so only its absence counts. Comparing
    its content would flag every ordinary edit to AGENTS.md or CLAUDE.md as drift.
    Status commands and doctor share this rule so they agree.

    A missing staged copy is *not* drift on its own, matching ``check_agent``: a fresh
    clone (or a `share` artifact, which has no staged copy at all) has a correct native
    file and nothing staged yet, and that must read as healthy rather than as drift.
    Staging only matters once it exists and disagrees with what apply would write.
    """
    if artifact.seed_only:
        return not native_path.exists()
    if not native_path.exists() or file_hash(native_path) != expected_hash:
        return True
    if artifact.root == "share" or not rendered.exists():
        return False
    return file_hash(rendered) != expected_hash


def resolve_config(
    adapter: AgentAdapter,
    scope: Scope,
    repo_root: Path,
    overrides: dict[str, Any] | None = None,
) -> tuple[MergeResult, list[tuple[str, dict[str, Any]]]]:
    """Resolve defaults, managed sources, and overrides in precedence order.

    Returns:
        The merged result and named input layers for provenance display.
    """
    defaults = adapter.defaults(scope)
    global_config = read_config(
        managed_config_path(adapter, global_root()), missing_ok=True
    )
    layers: list[tuple[str, dict[str, Any]]] = [
        ("defaults", defaults),
        ("global", global_config),
    ]
    if scope == "local":
        local_config = read_config(
            managed_config_path(adapter, project_scope_root(repo_root)), missing_ok=True
        )
        layers.append(("local", local_config))
    if overrides:
        layers.append(("overrides", overrides))
    return adapter.merge(*layers), layers


def apply_adapter(
    adapter: AgentAdapter,
    scope: Scope,
    repo_root: Path,
    *,
    overrides: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> list[OperationResult]:
    """Resolve once, then render or copy and sync every declared artifact.

    Raises:
        ValueError: The merged configuration fails adapter validation.
    """
    merged, _ = resolve_config(adapter, scope, repo_root, overrides)
    errors = adapter.validate(merged.config)
    if errors:
        raise ValueError("; ".join(errors))
    if not dry_run:
        scaffold_managed_source(adapter, scope_root(scope, repo_root), scope)
    return apply_resolved(
        adapter, scope, repo_root, merged, action="apply", dry_run=dry_run
    )


def sync_adapter(
    adapter: AgentAdapter,
    scope: Scope,
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> list[OperationResult]:
    """Copy every staged artifact to its native path without re-rendering.

    Raises:
        FileNotFoundError: A required managed copy does not exist.
    """
    root = scope_root(scope, repo_root)
    store = StateStore(root)
    results: list[OperationResult] = []
    # Collected and written once at the end rather than per artifact: a single
    # read-modify-write cycle cannot interleave with a concurrent invocation
    # part-way through the adapter's artifact list.
    recorded: list[tuple[Path, str, str]] = []
    for artifact in adapter.artifacts(scope):
        native = adapter.native_path(scope, repo_root, artifact)
        rendered = managed_copy_path(adapter, root, scope, artifact, native)
        if artifact.seed_only and native.is_file():
            results.append(seeded_result(adapter, artifact, "sync", native, rendered))
            continue
        if not rendered.is_file():
            raise FileNotFoundError(
                f"No rendered artifact for {adapter.name}/{artifact.key}: {rendered}"
            )
        content = rendered.read_bytes()
        digest = content_hash(content)
        current_hash = file_hash(native)
        mode_changed = mode_differs(native, artifact)
        changed = current_hash != digest or mode_changed
        diff = content_diff(content, native, rendered)
        if dry_run:
            results.append(
                OperationResult(
                    adapter.name,
                    artifact.key,
                    "sync",
                    changed,
                    native,
                    rendered,
                    diff,
                    message="dry-run",
                )
            )
            continue

        prior = store.get(native)
        backup = None
        if (
            native.is_file()
            and current_hash != digest
            and (prior is None or prior.get("hash") != current_hash)
        ):
            backup = backup_file(native, root)
        if current_hash != digest:
            atomic_write(native, content, mode=artifact.mode)
        elif mode_changed:
            os.chmod(native, 0o755)
        recorded.append((native, digest, "rendered"))
        results.append(
            OperationResult(
                adapter.name,
                artifact.key,
                "sync",
                changed,
                native,
                rendered,
                diff,
                backup,
            )
        )
    if recorded:
        store.record_many(recorded)
    return results


def apply_resolved(
    adapter: AgentAdapter,
    scope: Scope,
    repo_root: Path,
    merged: MergeResult,
    *,
    action: str,
    dry_run: bool,
) -> list[OperationResult]:
    root = scope_root(scope, repo_root)
    store = StateStore(root)
    results: list[OperationResult] = []
    # Collected and written once at the end rather than per artifact: a single
    # read-modify-write cycle cannot interleave with a concurrent invocation
    # part-way through the adapter's artifact list.
    recorded: list[tuple[Path, str, str]] = []
    for artifact in adapter.artifacts(scope):
        content = adapter.render_artifact(artifact, merged.config, scope)
        native = adapter.native_path(scope, repo_root, artifact)
        rendered = managed_copy_path(adapter, root, scope, artifact, native)
        if artifact.seed_only and native.is_file():
            results.append(seeded_result(adapter, artifact, action, native, rendered))
            continue
        digest = content_hash(content)
        current_hash = file_hash(native)
        rendered_hash = file_hash(rendered)
        mode_changed = mode_differs(native, artifact)
        changed = current_hash != digest or rendered_hash != digest or mode_changed
        diff = content_diff(content, native, rendered)
        if dry_run:
            results.append(
                OperationResult(
                    adapter.name,
                    artifact.key,
                    action,
                    changed,
                    native,
                    rendered,
                    diff,
                    message="dry-run",
                )
            )
            continue

        prior = store.get(native)
        backup = None
        drifted = False
        if native.is_file() and current_hash != digest:
            if prior is None or prior.get("hash") != current_hash:
                backup = backup_file(native, root)
                drifted = prior is not None

        mode = artifact.mode
        if rendered_hash != digest:
            atomic_write(rendered, content, mode=mode)
        elif artifact.executable and mode_differs(rendered, artifact):
            os.chmod(rendered, 0o755)
        if native != rendered and current_hash != digest:
            atomic_write(native, content, mode=mode)
        elif native != rendered and mode_changed:
            os.chmod(native, 0o755)

        source_layer = (
            highest_source(merged.provenance)
            if artifact.key == "config"
            else "packaged"
        )
        recorded.append((native, digest, source_layer))
        results.append(
            OperationResult(
                adapter.name,
                artifact.key,
                action,
                changed,
                native,
                rendered,
                diff,
                backup,
                message="drift detected" if drifted else "",
            )
        )
    if recorded:
        store.record_many(recorded)
    return results
