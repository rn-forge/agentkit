"""Repository-scope commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from ..core.config import parse_cli_overrides
from ..core.diff import layered_changes
from ..core.manager import (
    apply_adapter,
    init_adapter,
    managed_config_path,
    project_root,
    resolve_config,
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

app = typer.Typer(
    help="Manage repository-local agent configuration.", no_args_is_help=True
)


@app.command("init")
def init_command(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(
        None, "--agent", "-a", help="Agent(s); default is all."
    ),
    repo: Path = typer.Option(Path.cwd(), "--repo", help="Repository directory."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show changes without writing."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Scaffold .agentkit sources in a repository."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    root = project_root(repo)
    try:
        results = [
            init_adapter(item, root, dry_run=dry_run) for item in selected(agent)
        ]
    except OSError as exc:
        fail(str(exc))
    emit_operations(ctx, results)


@app.command("update")
def update_command(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(
        None, "--agent", "-a", help="Agent(s); default is all."
    ),
    set_value: list[str] | None = typer.Option(
        None, "--set", help="Override dotted KEY=VALUE."
    ),
    repo: Path = typer.Option(Path.cwd(), "--repo", help="Repository directory."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show changes without writing."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Re-render and sync repository-local configuration."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    root = project_root(repo)
    try:
        overrides = parse_cli_overrides(set_value or [])
        results = [
            apply_adapter(item, "local", root, overrides=overrides, dry_run=dry_run)
            for item in selected(agent)
        ]
    except (OSError, ValueError) as exc:
        fail(str(exc))
    emit_operations(ctx, results)


@app.command("status")
def status_command(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(
        None, "--agent", "-a", help="Agent(s); default is all."
    ),
    repo: Path = typer.Option(Path.cwd(), "--repo", help="Repository directory."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show project initialization and native drift."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    root = project_root(repo)
    scope = root / ".agentkit"
    rows = []
    for adapter in selected(agent):
        config = managed_config_path(adapter, scope)
        rendered = adapter.rendered_path(scope, "local")
        native = adapter.local_native_path(root)
        _, layers = resolve_config(adapter, "local", root)
        local_overrides = [
            change.path for change in layered_changes(layers) if change.layer == "local"
        ]
        rows.append(
            {
                "agent": adapter.name,
                "initialized": config.exists(),
                "rendered": rendered.exists(),
                "native": str(native),
                "drift": rendered.exists() and file_hash(rendered) != file_hash(native),
                "local_overrides": local_overrides,
            }
        )
    if options(ctx)["json"]:
        emit(ctx, rows)
        return
    if options(ctx)["quiet"]:
        typer.echo(
            "\n".join(f"{r['agent']}:{'drift' if r['drift'] else 'ok'}" for r in rows)
        )
        return
    table = Table(
        "Agent", "Initialized", "Rendered", "Local overrides", "Drift", "Native path"
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
