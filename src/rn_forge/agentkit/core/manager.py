"""Orchestrate config resolution, artifact writes, state, drift, and backups.

CLI commands call this module after selecting adapters; adapters supply schema,
rendering, and artifact declarations while I/O and state helpers perform writes.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from ..agents.base import AgentAdapter, Scope
from .artifacts import Artifact
from .config import ConfigMerger, MergeResult, defaults_for
from .diff import unified_diff
from .io import (
    atomic_write,
    read_config,
    read_config_document,
    update_config,
    write_config_document,
)
from .paths import global_root, project_scope_root
from .state import StateStore, backup_file, content_hash, file_hash


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Outcome of one action on one managed artifact."""

    agent: str
    artifact: str
    action: str
    changed: bool
    native_path: Path
    rendered_path: Path
    diff: str = ""
    backup_path: Path | None = None
    message: str = ""


def project_root(start: Path | None = None) -> Path:
    """Locate the nearest repository root, falling back to the start directory."""
    current = (start or Path.cwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def artifact_drifted(
    artifact: Artifact,
    native_path: Path,
    rendered: Path,
    expected_hash: str,
) -> bool:
    """Report whether one artifact differs from what apply would write.

    A seed artifact is written once and then owned by the user — apply leaves it alone
    (see ``_apply_resolved``) and diff skips it — so only its absence counts. Comparing
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


def scope_root(scope: Scope, repo_root: Path) -> Path:
    """Return the global or repository-local agentkit working-data root."""
    return global_root() if scope == "global" else project_scope_root(repo_root)


def managed_config_path(adapter: AgentAdapter, root: Path) -> Path:
    """Return an adapter's managed source path beneath a scope root."""
    return Path(root) / adapter.name / "config.toml"


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
    return _apply_resolved(
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
        rendered = _managed_copy_path(adapter, root, scope, artifact, native)
        if artifact.seed_only and native.is_file():
            results.append(_seeded_result(adapter, artifact, "sync", native, rendered))
            continue
        if not rendered.is_file():
            raise FileNotFoundError(
                f"No rendered artifact for {adapter.name}/{artifact.key}: {rendered}"
            )
        content = rendered.read_bytes()
        digest = content_hash(content)
        current_hash = file_hash(native)
        mode_changed = _mode_differs(native, artifact)
        changed = current_hash != digest or mode_changed
        diff = _content_diff(content, native, rendered)
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
            atomic_write(native, content, mode=_artifact_mode(artifact))
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
        return _apply_resolved(
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
    atomic_write(source_path, _managed_source_scaffold(adapter, "global"))
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


def init_adapter(
    adapter: AgentAdapter,
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> OperationResult:
    """Scaffold an inheriting project config without overwriting existing source."""
    root = project_scope_root(repo_root)
    config_path = managed_config_path(adapter, root)
    artifact = adapter.primary_artifact("local")
    rendered = adapter.rendered_path(root, "local", artifact)
    native = adapter.native_path("local", repo_root, artifact)
    if config_path.exists():
        return OperationResult(
            adapter.name,
            artifact.key,
            "init",
            False,
            native,
            rendered,
            message="already initialized",
        )
    if not dry_run:
        scaffold_managed_source(adapter, root, "local")
    return OperationResult(
        adapter.name,
        artifact.key,
        "init",
        True,
        native,
        rendered,
        message="dry-run" if dry_run else "initialized",
    )


_MANAGED_SOURCE_HEADER = """\
# agentkit managed source — {agent}, {scope} scope.
#
# Keys set here override the packaged {scope} defaults and are merged into every
# rendered {agent} artifact. This file is the layer you edit by hand; it is also
# where `agentkit diff --scope {scope} --write` captures native changes.
#
# An empty file means "no {scope} overrides" — the packaged defaults apply as-is.
"""


def _managed_source_scaffold(adapter: AgentAdapter, scope: Scope) -> str:
    """Return the documented empty-override scaffold for one adapter and scope."""
    return _MANAGED_SOURCE_HEADER.format(agent=adapter.name, scope=scope)


def scaffold_managed_source(adapter: AgentAdapter, root: Path, scope: Scope) -> bool:
    """Create a documented empty managed source when the scope has none.

    Returns:
        ``True`` when a new file was written.
    """
    config_path = managed_config_path(adapter, root)
    if config_path.exists():
        return False
    atomic_write(config_path, _managed_source_scaffold(adapter, scope))
    return True


def capture_adapter(
    adapter: AgentAdapter,
    scope: Scope,
    repo_root: Path,
) -> OperationResult:
    """Capture structural native-config additions and changes into managed source.

    The baseline is rendered from the persisted layers in memory rather than read
    from ``rendered/``: that staging copy is disposable — it is gitignored, so a
    fresh clone has none — and it can be stale, which would capture drift the
    user never made.

    Append-merged lists capture only a suffix added to the rendered value. Key
    removals and destructive edits to append-merged lists cannot be represented
    by the current layered merge model and are rejected.

    A scope with no native config yet has nothing to capture, and reports that
    instead of failing, so ``diff --write`` still shows the drift it found.

    Raises:
        ValueError: Native config is invalid or contains an unsupported removal.
    """
    root = scope_root(scope, repo_root)
    artifact = adapter.primary_artifact(scope)
    native = adapter.native_path(scope, repo_root, artifact)
    rendered = _managed_copy_path(adapter, root, scope, artifact, native)
    if not native.is_file():
        return OperationResult(
            adapter.name,
            artifact.key,
            "capture",
            False,
            native,
            rendered,
            message="no native config",
        )

    merged, _ = resolve_config(adapter, scope, repo_root)
    expected = adapter.parse_native_text(
        adapter.render(merged.config, scope=scope), artifact
    )
    actual = adapter.parse_native(native)
    errors = adapter.validate(actual)
    if errors:
        raise ValueError("; ".join(errors))

    source = managed_config_path(adapter, root)
    managed = read_config(source, missing_ok=True)
    updates, unsupported = _capture_updates(
        expected,
        actual,
        managed,
        ConfigMerger(adapter.schema()).append_paths,
    )
    if unsupported:
        paths = ", ".join(sorted(unsupported))
        raise ValueError(
            "Cannot capture removals or destructive append-list edits: " + paths
        )
    if updates:
        update_config(source, updates)
    return OperationResult(
        adapter.name,
        artifact.key,
        "capture",
        bool(updates),
        native,
        rendered,
        message="captured" if updates else "unchanged",
    )


def capture_assets(
    adapter: AgentAdapter,
    scope: Scope,
    repo_root: Path,
) -> list[OperationResult]:
    """Capture hand-edited native hooks/skills back into their packaged source.

    Only artifacts backed by a packaged static source file are eligible — templated and
    primary-config artifacts are unaffected, and are handled by :func:`capture_adapter`
    instead. A source outside this checkout (for example an installed, non-editable
    package) is reported as unwritable rather than raising, since running ``diff
    --write`` should still finish.
    """
    results: list[OperationResult] = []
    for artifact in adapter.artifacts(scope):
        if artifact.source is None:
            continue
        native = adapter.native_path(scope, repo_root, artifact)
        if not native.is_file():
            continue
        native_bytes = native.read_bytes()
        source_bytes = (
            artifact.source.read_bytes() if artifact.source.is_file() else b""
        )
        if native_bytes == source_bytes:
            continue
        try:
            atomic_write(artifact.source, native_bytes)
        except OSError as exc:
            results.append(
                OperationResult(
                    adapter.name,
                    artifact.key,
                    "capture-asset",
                    False,
                    native,
                    artifact.source,
                    message=f"unwritable: {exc}",
                )
            )
            continue
        results.append(
            OperationResult(
                adapter.name,
                artifact.key,
                "capture-asset",
                True,
                native,
                artifact.source,
                message="captured",
            )
        )
    return results


def capture_defaults(
    adapter: AgentAdapter,
    scope: Scope,
    repo_root: Path,
) -> OperationResult:
    """Promote a scope's managed overrides into the packaged scope defaults.

    Structural counterpart to :func:`capture_assets` for the primary config
    artifact: where ``capture_adapter`` folds native drift into the scope's
    managed ``config.toml``, this folds that managed override into the packaged
    defaults file :meth:`AgentAdapter.defaults` reads, so a fresh install picks
    it up as the new default. Only the values already captured to this scope's
    own managed source are considered — a local scope's promotion never pulls in
    the global layer that also feeds its resolved config.

    Only does something useful running from an editable checkout of this repo:
    an unwritable packaged defaults file (an installed, non-editable package) is
    reported instead of raising, the same as ``capture_assets``. An adapter with
    no packaged defaults file for this scope has nothing to promote into, and
    reports that instead of failing.

    Raises:
        ValueError: The managed override contains an unsupported removal.
    """
    target = adapter.defaults_path(scope)
    source = managed_config_path(adapter, scope_root(scope, repo_root))
    if target is None:
        return OperationResult(
            adapter.name,
            "config",
            "capture-defaults",
            False,
            source,
            source,
            message="no packaged defaults for this scope",
        )
    managed = read_config(source, missing_ok=True)
    if not managed:
        return OperationResult(
            adapter.name,
            "config",
            "capture-defaults",
            False,
            source,
            target,
            message="no managed overrides",
        )

    schema = adapter.schema()
    schema_defaults = defaults_for(schema)
    merger = ConfigMerger(schema)
    packaged = read_config(target, missing_ok=True)
    expected = merger.merge(schema_defaults, packaged).config
    actual = merger.merge(schema_defaults, packaged, managed).config
    updates, unsupported = _capture_updates(
        expected, actual, packaged, merger.append_paths
    )
    if unsupported:
        paths = ", ".join(sorted(unsupported))
        raise ValueError(
            "Cannot promote removals or destructive append-list edits: " + paths
        )
    if not updates:
        return OperationResult(
            adapter.name,
            "config",
            "capture-defaults",
            False,
            source,
            target,
            message="unchanged",
        )
    try:
        update_config(target, updates)
    except OSError as exc:
        return OperationResult(
            adapter.name,
            "config",
            "capture-defaults",
            False,
            source,
            target,
            message=f"unwritable: {exc}",
        )
    return OperationResult(
        adapter.name,
        "config",
        "capture-defaults",
        True,
        source,
        target,
        message="captured",
    )


def _capture_updates(
    expected: dict[str, Any],
    actual: dict[str, Any],
    managed: dict[str, Any],
    append_paths: set[str],
    prefix: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Return a managed-layer update that represents native structural drift."""
    updates: dict[str, Any] = {}
    unsupported: list[str] = []
    keys = [*actual, *(key for key in expected if key not in actual)]
    for key in keys:
        path = f"{prefix}.{key}" if prefix else key
        if key not in actual:
            unsupported.append(path)
            continue
        if key not in expected:
            updates[key] = actual[key]
            continue
        before = expected[key]
        after = actual[key]
        if before == after:
            continue
        current = managed.get(key)
        if isinstance(before, dict) and isinstance(after, dict):
            nested, rejected = _capture_updates(
                cast(dict[str, Any], before),
                cast(dict[str, Any], after),
                cast(dict[str, Any], current) if isinstance(current, dict) else {},
                append_paths,
                path,
            )
            if nested:
                updates[key] = nested
            unsupported.extend(rejected)
        elif (
            path in append_paths
            and isinstance(before, list)
            and isinstance(after, list)
        ):
            before_list = cast(list[Any], before)
            after_list = cast(list[Any], after)
            if after_list[: len(before_list)] != before_list:
                unsupported.append(path)
                continue
            additions = after_list[len(before_list) :]
            if additions:
                existing = cast(list[Any], current) if isinstance(current, list) else []
                updates[key] = [*existing, *additions]
        else:
            updates[key] = after
    return updates, unsupported


def _apply_resolved(
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
        rendered = _managed_copy_path(adapter, root, scope, artifact, native)
        if artifact.seed_only and native.is_file():
            results.append(_seeded_result(adapter, artifact, action, native, rendered))
            continue
        digest = content_hash(content)
        current_hash = file_hash(native)
        rendered_hash = file_hash(rendered)
        mode_changed = _mode_differs(native, artifact)
        changed = current_hash != digest or rendered_hash != digest or mode_changed
        diff = _content_diff(content, native, rendered)
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

        mode = _artifact_mode(artifact)
        if rendered_hash != digest:
            atomic_write(rendered, content, mode=mode)
        elif artifact.executable and _mode_differs(rendered, artifact):
            os.chmod(rendered, 0o755)
        if native != rendered and current_hash != digest:
            atomic_write(native, content, mode=mode)
        elif native != rendered and mode_changed:
            os.chmod(native, 0o755)

        source_layer = (
            _highest_source(merged.provenance)
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


def _managed_copy_path(
    adapter: AgentAdapter,
    root: Path,
    scope: Scope,
    artifact: Artifact,
    native: Path,
) -> Path:
    if artifact.root == "share":
        return native
    return adapter.rendered_path(root, scope, artifact)


def _content_diff(content: str | bytes, native: Path, rendered: Path) -> str:
    if file_hash(native) == content_hash(content):
        return ""
    if isinstance(content, bytes):
        try:
            expected = content.decode("utf-8")
        except UnicodeDecodeError:
            return f"binary artifact differs: {native}\n"
    else:
        expected = content
    try:
        actual = native.read_text(encoding="utf-8") if native.is_file() else ""
    except UnicodeDecodeError:
        return f"binary artifact differs: {native}\n"
    return unified_diff(
        expected,
        actual,
        expected_name=str(rendered),
        actual_name=str(native),
    )


def _seeded_result(
    adapter: AgentAdapter,
    artifact: Artifact,
    action: str,
    native: Path,
    rendered: Path,
) -> OperationResult:
    """Report a seed-only artifact that already exists as left untouched."""
    return OperationResult(
        adapter.name,
        artifact.key,
        action,
        False,
        native,
        rendered,
        message="exists; owned by the repository",
    )


def _artifact_mode(artifact: Artifact) -> int | None:
    return 0o755 if artifact.executable else None


def _mode_differs(path: Path, artifact: Artifact) -> bool:
    return (
        artifact.executable and path.is_file() and path.stat().st_mode & 0o777 != 0o755
    )


def _highest_source(provenance: dict[str, str]) -> str:
    priority = {"defaults": 0, "global": 1, "local": 2, "overrides": 3}
    return max(
        provenance.values(), key=lambda name: priority.get(name, -1), default="defaults"
    )
