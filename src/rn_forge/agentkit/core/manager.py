"""High-level render, sync, scaffold, and resolution operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..agents.base import AgentAdapter, Scope
from .config import MergeResult
from .diff import unified_diff
from .io import atomic_write, read_config, write_config
from .state import StateStore, backup_file, content_hash, file_hash


@dataclass(frozen=True, slots=True)
class OperationResult:
    agent: str
    action: str
    changed: bool
    native_path: Path
    rendered_path: Path
    diff: str = ""
    backup_path: Path | None = None
    message: str = ""


def global_root() -> Path:
    return Path.home() / ".agentkit"


def project_root(start: Path | None = None) -> Path:
    """Locate the nearest repository root, falling back to the start directory."""
    current = (start or Path.cwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def scope_root(scope: Scope, repo_root: Path) -> Path:
    return global_root() if scope == "global" else Path(repo_root) / ".agentkit"


def managed_config_path(adapter: AgentAdapter, root: Path) -> Path:
    return Path(root) / adapter.name / "config.toml"


def resolve_config(
    adapter: AgentAdapter,
    scope: Scope,
    repo_root: Path,
    overrides: dict[str, Any] | None = None,
) -> tuple[MergeResult, list[tuple[str, dict[str, Any]]]]:
    """Resolve defaults/global/local/overrides and retain layers for display."""
    defaults = adapter.defaults()
    global_config = read_config(
        managed_config_path(adapter, global_root()), missing_ok=True
    )
    layers: list[tuple[str, dict[str, Any]]] = [
        ("defaults", defaults),
        ("global", global_config),
    ]
    if scope == "local":
        local_config = read_config(
            managed_config_path(adapter, Path(repo_root) / ".agentkit"), missing_ok=True
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
) -> OperationResult:
    """Resolve, validate, render into staging, and sync to a native path."""
    root = scope_root(scope, repo_root)
    merged, _ = resolve_config(adapter, scope, repo_root, overrides)
    errors = adapter.validate(merged.config)
    if errors:
        raise ValueError("; ".join(errors))
    rendered_content = adapter.render(merged.config, scope=scope)
    rendered_path = adapter.rendered_path(root, scope)
    native_path = adapter.native_path(scope, repo_root)
    actual = native_path.read_text(encoding="utf-8") if native_path.is_file() else ""
    diff = unified_diff(
        rendered_content,
        actual,
        expected_name=str(rendered_path),
        actual_name=str(native_path),
    )
    digest = content_hash(rendered_content)
    changed = file_hash(native_path) != digest or file_hash(rendered_path) != digest
    if dry_run:
        return OperationResult(
            adapter.name,
            "apply",
            changed,
            native_path,
            rendered_path,
            diff=diff,
            message="dry-run",
        )

    store = StateStore(root)
    prior = store.get(native_path)
    current_hash = file_hash(native_path)
    if not changed and prior is not None and prior.get("hash") == digest:
        return OperationResult(
            adapter.name, "apply", False, native_path, rendered_path, diff
        )
    backup = None
    if native_path.is_file() and current_hash != digest:
        if prior is None or prior.get("hash") != current_hash:
            backup = backup_file(native_path, root)

    if file_hash(rendered_path) != digest:
        atomic_write(rendered_path, rendered_content)
    if current_hash != digest:
        atomic_write(native_path, rendered_content)
    source_layer = _highest_source(merged.provenance)
    store.record(native_path, digest, source_layer)
    return OperationResult(
        adapter.name, "apply", changed, native_path, rendered_path, diff, backup
    )


def sync_adapter(
    adapter: AgentAdapter,
    scope: Scope,
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> OperationResult:
    """Copy staged rendered content to the native path without re-rendering."""
    root = scope_root(scope, repo_root)
    rendered_path = adapter.rendered_path(root, scope)
    native_path = adapter.native_path(scope, repo_root)
    if not rendered_path.is_file():
        raise FileNotFoundError(
            f"No rendered config for {adapter.name}: {rendered_path}"
        )
    content = rendered_path.read_text(encoding="utf-8")
    actual = native_path.read_text(encoding="utf-8") if native_path.is_file() else ""
    digest = content_hash(content)
    changed = file_hash(native_path) != digest
    diff = unified_diff(
        content, actual, expected_name=str(rendered_path), actual_name=str(native_path)
    )
    if dry_run:
        return OperationResult(
            adapter.name,
            "sync",
            changed,
            native_path,
            rendered_path,
            diff,
            message="dry-run",
        )

    store = StateStore(root)
    prior = store.get(native_path)
    current_hash = file_hash(native_path)
    if not changed and prior is not None and prior.get("hash") == digest:
        return OperationResult(
            adapter.name, "sync", False, native_path, rendered_path, diff
        )
    backup = None
    if (
        native_path.is_file()
        and changed
        and (prior is None or prior.get("hash") != current_hash)
    ):
        backup = backup_file(native_path, root)
    if changed:
        atomic_write(native_path, content)
    store.record(native_path, digest, "rendered")
    return OperationResult(
        adapter.name, "sync", changed, native_path, rendered_path, diff, backup
    )


def reset_adapter(
    adapter: AgentAdapter,
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> OperationResult:
    """Replace global managed and native configuration with schema defaults."""
    root = global_root()
    native = adapter.global_native_path()
    rendered = adapter.render(adapter.defaults(), scope="global")
    actual = native.read_text(encoding="utf-8") if native.is_file() else ""
    diff = unified_diff(
        rendered, actual, expected_name="built-in defaults", actual_name=str(native)
    )
    if dry_run:
        return OperationResult(
            adapter.name,
            "reset",
            bool(diff),
            native,
            adapter.rendered_path(root, "global"),
            diff,
            message="dry-run",
        )

    backup = backup_file(native, root)
    write_config(managed_config_path(adapter, root), adapter.defaults())
    result = apply_adapter(adapter, "global", repo_root)
    return OperationResult(
        result.agent,
        "reset",
        result.changed,
        result.native_path,
        result.rendered_path,
        diff,
        backup,
    )


def init_adapter(
    adapter: AgentAdapter,
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> OperationResult:
    """Scaffold an inheriting project config, without overwriting existing source."""
    root = Path(repo_root) / ".agentkit"
    config_path = managed_config_path(adapter, root)
    rendered = adapter.rendered_path(root, "local")
    native = adapter.local_native_path(repo_root)
    if config_path.exists():
        return OperationResult(
            adapter.name, "init", False, native, rendered, message="already initialized"
        )
    if not dry_run:
        write_config(config_path, {})
    return OperationResult(
        adapter.name,
        "init",
        True,
        native,
        rendered,
        message="dry-run" if dry_run else "initialized",
    )


def _highest_source(provenance: dict[str, str]) -> str:
    priority = {"defaults": 0, "global": 1, "local": 2, "overrides": 3}
    return max(
        provenance.values(), key=lambda name: priority.get(name, -1), default="defaults"
    )
