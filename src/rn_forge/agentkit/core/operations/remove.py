"""Reset, strip hook wiring from, and delete artifacts owned by an adapter."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import replace
from pathlib import Path

from ...agents.base import AgentAdapter, Scope
from ..io import atomic_write, read_config_document, write_config_document
from ..paths import global_root, managed_config_path, scope_root
from ..state import StateStore, backup_file, file_hash
from .apply import apply_resolved, apply_adapter
from .result import OperationResult


def reset_adapter(
    adapter: AgentAdapter,
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> list[OperationResult]:
    """Restore the empty managed override, then re-apply packaged defaults.

    The managed source and the native primary config are both backed up first, so a
    hand-edited override (comments included) is recoverable after a reset.
    """
    root = global_root()
    defaults = adapter.defaults("global")
    if dry_run:
        merged = adapter.merge(("defaults", defaults))
        return apply_resolved(
            adapter, "global", repo_root, merged, action="reset", dry_run=True
        )

    primary = adapter.global_native_path()
    backup = backup_file(primary, root)
    source_path = managed_config_path(adapter, root)
    source_backup = backup_file(source_path, root)
    # Reset restores the *empty override scaffold*, not materialized defaults.
    # Writing defaults here would turn them into an override layer that the
    # apply below merges on top of the packaged defaults a second time —
    # doubling every append-merged list (see Claude's permission lists).
    atomic_write(source_path, adapter.managed_source_scaffold("global"))
    results = apply_adapter(adapter, "global", repo_root)
    reset_results = [replace(result, action="reset") for result in results]
    if backup is not None or source_backup is not None:
        note = (
            f"managed source backed up to {source_backup}"
            if source_backup is not None
            else ""
        )
        reset_results = [
            replace(result, backup_path=backup or result.backup_path, message=note)
            if result.artifact == "config"
            else result
            for result in reset_results
        ]
    return reset_results


def strip_native_hooks(
    adapter: AgentAdapter,
    scope: Scope,
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> OperationResult:
    """Remove agentkit's hook registrations from the primary native config, in place.

    Used by ``agentkit uninstall`` / ``agentkit project remove`` to stop an agent from
    invoking hook scripts that are about to disappear, without discarding the rest of a
    native file that stays meaningful on its own — Claude's ``permissions.deny`` and
    ``outputStyle`` in particular. The native file is parsed as a generic round-trip
    document (preserving comments and any content agentkit did not write, such as
    permission grants a user added at runtime) rather than through the adapter's typed
    schema, and only its top-level ``hooks`` key is dropped, if present. A backup is
    taken first, same as any other native overwrite.
    """
    artifact = adapter.primary_artifact(scope)
    native = adapter.native_path(scope, repo_root, artifact)
    root = scope_root(scope, repo_root)
    if not native.is_file():
        return OperationResult(
            adapter.name,
            artifact.key,
            "strip-hooks",
            False,
            native,
            native,
            message="no native config",
        )
    document = read_config_document(native)
    if not isinstance(document, MutableMapping) or "hooks" not in document:
        return OperationResult(
            adapter.name,
            artifact.key,
            "strip-hooks",
            False,
            native,
            native,
            message="no hook registrations",
        )
    if dry_run:
        return OperationResult(
            adapter.name,
            artifact.key,
            "strip-hooks",
            True,
            native,
            native,
            message="dry-run",
        )
    backup = backup_file(native, root)
    del document["hooks"]
    write_config_document(native, document)
    return OperationResult(
        adapter.name,
        artifact.key,
        "strip-hooks",
        True,
        native,
        native,
        backup_path=backup,
        message="hook registrations removed",
    )


def remove_owned_artifacts(
    adapter: AgentAdapter,
    scope: Scope,
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> list[OperationResult]:
    """Delete agent-rooted skill and hook-manifest files this adapter wrote.

    Used by ``agentkit uninstall`` / ``agentkit project remove`` to clean up
    ``~/.claude`` and ``~/.codex`` (or a repo's ``.claude``/``.codex``) beyond the
    primary config, which :func:`strip_native_hooks` edits instead of deleting. Only
    skill files and an adapter's :meth:`AgentAdapter.is_native_hook_artifact` files are
    in scope — never the primary config, a seed-only repo instruction file, or share-
    rooted hook scripts (removed by deleting the scope root itself). A file whose
    content no longer matches what agentkit last wrote is left alone and reported as
    drifted rather than deleted, the same drift-safety ``capture_assets`` relies on.
    """
    root = scope_root(scope, repo_root)
    store = StateStore(root)
    results: list[OperationResult] = []
    for artifact in adapter.artifacts(scope):
        if artifact.root != "agent" or artifact.seed_only or artifact.key == "config":
            continue
        if artifact.kind != "skill" and not adapter.is_native_hook_artifact(artifact):
            continue
        native = adapter.native_path(scope, repo_root, artifact)
        if not native.is_file():
            continue
        prior = store.get(native)
        current_hash = file_hash(native)
        if prior is not None and prior.get("hash") != current_hash:
            results.append(
                OperationResult(
                    adapter.name,
                    artifact.key,
                    "remove",
                    False,
                    native,
                    native,
                    message="modified since last apply; left in place",
                )
            )
            continue
        if dry_run:
            results.append(
                OperationResult(
                    adapter.name,
                    artifact.key,
                    "remove",
                    True,
                    native,
                    native,
                    message="dry-run",
                )
            )
            continue
        native.unlink()
        store.remove(native)
        boundary = Path.home() if scope == "global" else Path(repo_root)
        _prune_empty_dirs(native.parent, boundary.expanduser().resolve())
        results.append(
            OperationResult(
                adapter.name,
                artifact.key,
                "remove",
                True,
                native,
                native,
                message="removed",
            )
        )
    return results


def _prune_empty_dirs(start: Path, boundary: Path) -> None:
    """Remove now-empty directories a deleted artifact leaves behind.

    Walks upward from a just-deleted file's parent, stopping at the first directory that
    still holds something (a sibling skill, a native config file) or at the agent or
    repository root itself, which is never removed.
    """
    current = start.resolve()
    while current != boundary and current.is_dir() and not any(current.iterdir()):
        current.rmdir()
        current = current.parent
