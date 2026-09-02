"""Implement `agentkit global apply/sync/reset/list`.

These select adapters and delegate file operations to core.operations beneath
``$RNF_HOME/share/agentkit``.
"""

from __future__ import annotations

from typing import Any

import typer
from rich.table import Table

from ..core.config import parse_cli_overrides
from ..core.operations import (
    apply_adapter,
    artifact_drifted,
    resolve_config,
    reset_adapter,
    sync_adapter,
)
from ..core.paths import global_root, managed_config_path, project_root
from ..core.state import content_hash
from .base import BaseCommand, console


class GlobalCommand(BaseCommand):
    """Implement the ``global`` command group."""

    def apply(
        self,
        agent: list[str] | None,
        set_value: list[str] | None,
        dry_run: bool,
    ) -> None:
        """Render and sync global configuration."""
        self.warn_if_jq_missing()
        try:
            overrides = parse_cli_overrides(set_value or [])
            results = [
                result
                for item in self.selected(agent)
                for result in apply_adapter(
                    item, "global", project_root(), overrides=overrides, dry_run=dry_run
                )
            ]
        except (OSError, ValueError) as exc:
            self.fail(str(exc))
        self.emit_operations(results)

    def sync(self, agent: list[str] | None, dry_run: bool) -> None:
        """Re-sync staged global files without rendering."""
        try:
            results = [
                result
                for item in self.selected(agent)
                for result in sync_adapter(
                    item, "global", project_root(), dry_run=dry_run
                )
            ]
        except (OSError, ValueError) as exc:
            self.fail(str(exc))
        self.emit_operations(results)

    def reset(self, agent: list[str] | None, yes: bool, dry_run: bool) -> None:
        """Back up and restore global configuration to built-in defaults."""
        adapters = self.selected(agent)
        if not dry_run and not yes:
            names = ", ".join(item.name for item in adapters)
            if not typer.confirm(f"Reset global configuration for {names}?"):
                raise typer.Abort()
        try:
            results = [
                result
                for item in adapters
                for result in reset_adapter(item, project_root(), dry_run=dry_run)
            ]
        except (OSError, ValueError) as exc:
            self.fail(str(exc))
        self.emit_operations(results)

    def list(self) -> None:
        """List managed adapters and their global status."""
        rows: list[dict[str, Any]] = []
        # Rendering and config parsing happen here, so failures must surface as the
        # documented `error: ...` exit rather than a traceback.
        with self.boundary():
            for adapter in self.selected(None):
                config = managed_config_path(adapter, global_root())
                merged, _ = resolve_config(adapter, "global", project_root())
                artifacts = adapter.artifacts("global")
                paths = [
                    (
                        artifact,
                        adapter.native_path("global", project_root(), artifact),
                        adapter.native_path("global", project_root(), artifact)
                        if artifact.root == "share"
                        else adapter.rendered_path(global_root(), "global", artifact),
                        content_hash(
                            adapter.render_artifact(artifact, merged.config, "global")
                        ),
                    )
                    for artifact in artifacts
                ]
                native = adapter.global_native_path()
                rows.append(
                    {
                        "agent": adapter.name,
                        "configured": config.exists(),
                        "rendered": all(
                            rendered.exists()
                            for artifact, _, rendered, _ in paths
                            if not artifact.seed_only
                        ),
                        "native": str(native),
                        "in_sync": not any(artifact_drifted(*entry) for entry in paths),
                    }
                )
        if self.json_output:
            self.emit(rows)
            return
        if self.quiet:
            typer.echo("\n".join(row["agent"] for row in rows))
            return
        table = Table("Agent", "Managed", "Rendered", "In sync", "Native path")
        for row in rows:
            table.add_row(
                str(row["agent"]),
                "yes" if row["configured"] else "no",
                "yes" if row["rendered"] else "no",
                "yes" if row["in_sync"] else "no",
                str(row["native"]),
            )
        console.print(table)
