"""Implement `agentkit project init/update/status/remove`.

These locate repository roots, resolve local managed sources, and delegate artifact
writes to core.operations.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from ..core.config import parse_cli_overrides
from ..core.diff import layered_changes
from ..core.io import atomic_write
from ..core.operations import (
    OperationResult,
    apply_adapter,
    artifact_drifted,
    init_adapter,
    remove_owned_artifacts,
    resolve_config,
    strip_native_hooks,
)
from ..core.paths import managed_config_path, project_root, project_scope_root
from ..core.state import content_hash
from .base import BaseCommand, console

_GITIGNORE_START = "# BEGIN rn-forge agentkit"
_GITIGNORE_END = "# END rn-forge agentkit"
_GITIGNORE_ENTRIES = (
    ".rn-forge/agentkit/*/rendered/",
    ".rn-forge/agentkit/*/hooks/",
    ".rn-forge/agentkit/_common/",
    ".rn-forge/agentkit/state.json",
    ".rn-forge/agentkit/backups/",
)


def _scaffold_gitignore(root: Path, *, dry_run: bool) -> OperationResult:
    """Add the derived-data ignore block, refreshing stale entries in place."""
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    block = "\n".join((_GITIGNORE_START, *_GITIGNORE_ENTRIES, _GITIGNORE_END))
    start = existing.find(_GITIGNORE_START)
    end = existing.find(_GITIGNORE_END)
    if start != -1 and end > start:
        content = existing[:start] + block + existing[end + len(_GITIGNORE_END) :]
    else:
        separator = "" if not existing or existing.endswith("\n\n") else "\n"
        content = f"{existing}{separator}{block}\n"
    changed = content != existing
    if changed and not dry_run:
        atomic_write(path, content)
    return OperationResult(
        "project",
        ".gitignore",
        "init",
        changed,
        path,
        path,
        message="dry-run" if dry_run else "initialized",
    )


def _remove_gitignore_block(root: Path, *, dry_run: bool) -> OperationResult:
    """Remove the derived-data ignore block `init` added, if one is present."""
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start = existing.find(_GITIGNORE_START)
    end = existing.find(_GITIGNORE_END)
    if start == -1 or end <= start:
        return OperationResult(
            "project",
            ".gitignore",
            "remove",
            False,
            path,
            path,
            message="no agentkit block found",
        )
    content = existing[:start] + existing[end + len(_GITIGNORE_END) :]
    while "\n\n\n" in content:
        content = content.replace("\n\n\n", "\n\n")
    changed = content != existing
    if changed and not dry_run:
        atomic_write(path, content)
    return OperationResult(
        "project",
        ".gitignore",
        "remove",
        changed,
        path,
        path,
        message="dry-run" if dry_run else "removed",
    )


class ProjectCommand(BaseCommand):
    """Implement the ``project`` command group."""

    def init(self, agent: list[str] | None, repo: Path, dry_run: bool) -> None:
        """Scaffold, render, and sync rn-forge agentkit in a repository."""
        self.warn_if_jq_missing()
        root = project_root(repo)
        try:
            results: list[OperationResult] = []
            for item in self.selected(agent):
                results.append(init_adapter(item, root, dry_run=dry_run))
                results.extend(apply_adapter(item, "local", root, dry_run=dry_run))
            results.append(_scaffold_gitignore(root, dry_run=dry_run))
        except (OSError, ValueError) as exc:
            self.fail(str(exc))
        self.emit_operations(results)

    def update(
        self,
        agent: list[str] | None,
        set_value: list[str] | None,
        repo: Path,
        dry_run: bool,
    ) -> None:
        """Re-render and sync repository-local configuration."""
        root = project_root(repo)
        try:
            overrides = parse_cli_overrides(set_value or [])
            results = [
                result
                for item in self.selected(agent)
                for result in apply_adapter(
                    item, "local", root, overrides=overrides, dry_run=dry_run
                )
            ]
        except (OSError, ValueError) as exc:
            self.fail(str(exc))
        self.emit_operations(results)

    def status(self, agent: list[str] | None, repo: Path) -> None:
        """Show project initialization and native drift."""
        root = project_root(repo)
        scope = project_scope_root(root)
        rows: list[dict[str, Any]] = []
        # Rendering and config parsing happen here, so failures must surface as the
        # documented `error: ...` exit rather than a traceback.
        with self.boundary():
            for adapter in self.selected(agent):
                config = managed_config_path(adapter, scope)
                merged, layers = resolve_config(adapter, "local", root)
                artifacts = adapter.artifacts("local")
                paths = [
                    (
                        artifact,
                        adapter.native_path("local", root, artifact),
                        adapter.native_path("local", root, artifact)
                        if artifact.root == "share"
                        else adapter.rendered_path(scope, "local", artifact),
                        content_hash(
                            adapter.render_artifact(artifact, merged.config, "local")
                        ),
                    )
                    for artifact in artifacts
                ]
                native = adapter.local_native_path(root)
                local_overrides = [
                    change.path
                    for change in layered_changes(layers)
                    if change.layer == "local"
                ]
                rows.append(
                    {
                        "agent": adapter.name,
                        "initialized": config.exists(),
                        "rendered": all(
                            rendered.exists()
                            for artifact, _, rendered, _ in paths
                            if not artifact.seed_only
                        ),
                        "native": str(native),
                        "drift": any(artifact_drifted(*entry) for entry in paths),
                        "local_overrides": local_overrides,
                    }
                )
        if self.json_output:
            self.emit(rows)
            return
        if self.quiet:
            typer.echo(
                "\n".join(
                    f"{r['agent']}:{'drift' if r['drift'] else 'ok'}" for r in rows
                )
            )
            return
        table = Table(
            "Agent",
            "Initialized",
            "Rendered",
            "Local overrides",
            "Drift",
            "Native path",
        )
        for row in rows:
            table.add_row(
                str(row["agent"]),
                "yes" if row["initialized"] else "no",
                "yes" if row["rendered"] else "no",
                ", ".join(row["local_overrides"]) or "—",
                "yes" if row["drift"] else "no",
                str(row["native"]),
            )
        console.print(table)

    def remove(
        self, agent: list[str] | None, repo: Path, yes: bool, dry_run: bool
    ) -> None:
        """Undo `project init`/`update`: strip hook wiring, then this repo's working
        data.

        The repository-local counterpart to `agentkit uninstall`: removes agentkit's
        hook registrations from each adapter's repository-local native config (Codex's
        `.codex/hooks.json`; Claude's `.claude/settings.local.json` keeps its
        `permissions` block, only losing the `hooks` key) without touching anything
        else, then deletes repository-local hook-manifest files agentkit wrote. Seed
        files (`CLAUDE.md`, `AGENTS.md`) are never touched — they are repository-owned,
        not agentkit's to remove.

        `<repo>/.rn-forge/agentkit/` (managed sources, rendered state, and any
        repository-local backups) and the `.gitignore` block `init` added are asked
        about separately, since removing the working-data root is the one step here
        nothing can undo.
        """
        root = project_root(repo)
        data_root = project_scope_root(root)
        adapters = self.selected(agent)

        if not dry_run and not yes:
            names = ", ".join(item.name for item in adapters)
            if not typer.confirm(
                f"Remove agentkit's hook registrations and owned files for {names} in "
                f"{root}?"
            ):
                raise typer.Abort()

        results: list[OperationResult] = []
        with self.boundary():
            for adapter in adapters:
                results.append(
                    strip_native_hooks(adapter, "local", root, dry_run=dry_run)
                )
                results.extend(
                    remove_owned_artifacts(adapter, "local", root, dry_run=dry_run)
                )

        if not data_root.is_dir():
            remove_data, data_message = False, "already absent"
        elif dry_run:
            remove_data, data_message = True, "dry-run"
        elif yes or typer.confirm(
            f"Also remove {data_root}? This deletes the repository's managed sources, "
            "rendered state, and any repository-local backups — irreversible."
        ):
            remove_data, data_message = True, "removed"
            shutil.rmtree(data_root)
        else:
            remove_data, data_message = False, "kept — not confirmed"
        results.append(
            OperationResult(
                "project",
                "working-data",
                "remove",
                remove_data,
                data_root,
                data_root,
                message=data_message,
            )
        )
        if remove_data:
            results.append(_remove_gitignore_block(root, dry_run=dry_run))

        self.emit_operations(results)
