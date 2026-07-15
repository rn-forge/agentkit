"""Implement repository init, update, and status workflows.

These Typer commands locate repository roots, resolve local managed sources,
and delegate artifact writes to the core manager.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
from ..core.paths import project_scope_root
from ..core.state import content_hash, file_hash
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
    """Scaffold rn-forge agentkit sources in a repository."""
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
            result
            for item in selected(agent)
            for result in apply_adapter(
                item, "local", root, overrides=overrides, dry_run=dry_run
            )
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
    scope = project_scope_root(root)
    rows: list[dict[str, Any]] = []
    for adapter in selected(agent):
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
                content_hash(adapter.render_artifact(artifact, merged.config, "local")),
            )
            for artifact in artifacts
        ]
        native = adapter.local_native_path(root)
        local_overrides = [
            change.path for change in layered_changes(layers) if change.layer == "local"
        ]
        rows.append(
            {
                "agent": adapter.name,
                "initialized": config.exists(),
                "rendered": all(rendered.exists() for _, _, rendered, _ in paths),
                "native": str(native),
                "drift": any(
                    not rendered.exists()
                    or not native_path.exists()
                    or file_hash(native_path) != expected_hash
                    or (
                        artifact.root != "share"
                        and file_hash(rendered) != expected_hash
                    )
                    for artifact, native_path, rendered, expected_hash in paths
                ),
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
