"""Global-scope commands."""

from __future__ import annotations

import typer
from rich.table import Table

from ..core.config import parse_cli_overrides
from ..core.manager import (
    apply_adapter,
    global_root,
    managed_config_path,
    project_root,
    reset_adapter,
    sync_adapter,
)
from ..core.state import file_hash
from .common import (
    command_options,
    console,
    emit,
    emit_operations,
    fail,
    options,
    selected,
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
    try:
        overrides = parse_cli_overrides(set_value or [])
        results = [
            apply_adapter(
                item, "global", project_root(), overrides=overrides, dry_run=dry_run
            )
            for item in selected(agent)
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
            sync_adapter(item, "global", project_root(), dry_run=dry_run)
            for item in selected(agent)
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
            reset_adapter(item, project_root(), dry_run=dry_run) for item in adapters
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
    rows = []
    for adapter in selected(None):
        config = managed_config_path(adapter, global_root())
        rendered = adapter.rendered_path(global_root(), "global")
        native = adapter.global_native_path()
        rows.append(
            {
                "agent": adapter.name,
                "configured": config.exists(),
                "rendered": rendered.exists(),
                "native": str(native),
                "in_sync": rendered.exists()
                and file_hash(rendered) == file_hash(native),
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
