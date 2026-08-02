"""Implement global apply, sync, reset, and status-list workflows.

These Typer commands select adapters and delegate file operations to the core
manager beneath ``$RNF_HOME/share/agentkit``.
"""

from __future__ import annotations

from typing import Any

import typer
from rich.table import Table

from ..core.config import parse_cli_overrides
from ..core.manager import (
    apply_adapter,
    managed_config_path,
    project_root,
    resolve_config,
    reset_adapter,
    sync_adapter,
)
from ..core.paths import global_root
from ..core.state import content_hash, file_hash
from .common import (
    command_options,
    console,
    emit,
    emit_operations,
    fail,
    options,
    selected,
    warn_if_jq_missing,
)

app = typer.Typer(help="Manage user-wide agent configuration.", no_args_is_help=True)


@app.command("apply")
def apply_command(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(
        None, "--agent", "-a", help="Agent(s); default is all."
    ),
    set_value: list[str] | None = typer.Option(
        None, "--set", help="Override dotted KEY=VALUE."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show changes without writing."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Render and sync global configuration."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    warn_if_jq_missing()
    try:
        overrides = parse_cli_overrides(set_value or [])
        results = [
            result
            for item in selected(agent)
            for result in apply_adapter(
                item, "global", project_root(), overrides=overrides, dry_run=dry_run
            )
        ]
    except (OSError, ValueError) as exc:
        fail(str(exc))
    emit_operations(ctx, results)


@app.command("sync")
def sync_command(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(
        None, "--agent", "-a", help="Agent(s); default is all."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show changes without writing."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Re-sync staged global files without rendering."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    try:
        results = [
            result
            for item in selected(agent)
            for result in sync_adapter(item, "global", project_root(), dry_run=dry_run)
        ]
    except (OSError, ValueError) as exc:
        fail(str(exc))
    emit_operations(ctx, results)


@app.command("reset")
def reset_command(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(
        None, "--agent", "-a", help="Agent(s); default is all."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show changes without writing."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Back up and restore global configuration to built-in defaults."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    adapters = selected(agent)
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
        fail(str(exc))
    emit_operations(ctx, results)


@app.command("list")
def list_command(
    ctx: typer.Context,
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List managed adapters and their global status."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    rows: list[dict[str, Any]] = []
    for adapter in selected(None):
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
                "rendered": all(rendered.exists() for _, _, rendered, _ in paths),
                "native": str(native),
                "in_sync": all(
                    rendered.exists()
                    and native_path.exists()
                    and file_hash(native_path) == expected_hash
                    and (
                        artifact.root == "share" or file_hash(rendered) == expected_hash
                    )
                    for artifact, native_path, rendered, expected_hash in paths
                ),
            }
        )
    if options(ctx)["json"]:
        emit(ctx, rows)
        return
    if options(ctx)["quiet"]:
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
