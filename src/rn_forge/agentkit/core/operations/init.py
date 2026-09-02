"""Scaffold a repository-local managed source without overwriting existing input."""

from __future__ import annotations

from pathlib import Path

from ...agents.base import AgentAdapter, Scope
from ..io import atomic_write
from ..paths import managed_config_path, project_scope_root
from .result import OperationResult


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


def scaffold_managed_source(adapter: AgentAdapter, root: Path, scope: Scope) -> bool:
    """Create a documented empty managed source when the scope has none.

    Returns:
        ``True`` when a new file was written.
    """
    config_path = managed_config_path(adapter, root)
    if config_path.exists():
        return False
    atomic_write(config_path, adapter.managed_source_scaffold(scope))
    return True
