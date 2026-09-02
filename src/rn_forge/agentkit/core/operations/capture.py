"""Fold native drift back into managed source, packaged assets, and defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from ...agents.base import AgentAdapter, Scope
from ..config import ConfigMerger, defaults_for
from ..io import atomic_write, read_config, update_config
from ..paths import managed_config_path, scope_root
from .apply import resolve_config
from .result import OperationResult, managed_copy_path


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
    rendered = managed_copy_path(adapter, root, scope, artifact, native)
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
