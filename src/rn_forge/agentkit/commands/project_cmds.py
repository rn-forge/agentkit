"""Implement repository init, update, and status workflows.

These Typer commands locate repository roots, resolve local managed sources, and
delegate artifact writes to the core manager.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from ..core.config import parse_cli_overrides
from ..core.diff import layered_changes
from ..core.io import atomic_write
from ..core.manager import (
    OperationResult,
    apply_adapter,
    artifact_drifted,
    init_adapter,
    managed_config_path,
    project_root,
    resolve_config,
)
from ..core.paths import project_scope_root
from ..core.state import content_hash
from .common import (
    command_boundary,
    AGENT_HELP,
    DRY_RUN_HELP,
    JSON_HELP,
    QUIET_HELP,
    REPO_HELP,
    command_options,
    console,
    emit,
    emit_operations,
    fail,
    options,
    selected,
    warn_if_jq_missing,
)

app = typer.Typer(
    help="Manage repository-local agent configuration.", no_args_is_help=True
)

_GITIGNORE_START = "# BEGIN rn-forge agentkit"
_GITIGNORE_END = "# END rn-forge agentkit"
_GITIGNORE_ENTRIES = (
    ".rn-forge/agentkit/*/rendered/",
    ".rn-forge/agentkit/*/hooks/",
    ".rn-forge/agentkit/_common/",
    ".rn-forge/agentkit/state.json",
    ".rn-forge/agentkit/backups/",
)


@app.command("init")
def init_command(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
    repo: Path = typer.Option(Path.cwd(), "--repo", help=REPO_HELP),
    dry_run: bool = typer.Option(False, "--dry-run", help=DRY_RUN_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Scaffold, render, and sync rn-forge agentkit in a repository."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    warn_if_jq_missing()
    root = project_root(repo)
    try:
        results: list[OperationResult] = []
        for item in selected(agent):
            results.append(init_adapter(item, root, dry_run=dry_run))
            results.extend(apply_adapter(item, "local", root, dry_run=dry_run))
        results.append(_scaffold_gitignore(root, dry_run=dry_run))
    except (OSError, ValueError) as exc:
        fail(str(exc))
    emit_operations(ctx, results)


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


@app.command("update")
def update_command(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
    set_value: list[str] | None = typer.Option(
        None, "--set", help="Override dotted KEY=VALUE."
    ),
    repo: Path = typer.Option(Path.cwd(), "--repo", help=REPO_HELP),
    dry_run: bool = typer.Option(False, "--dry-run", help=DRY_RUN_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
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
    agent: list[str] | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
    repo: Path = typer.Option(Path.cwd(), "--repo", help=REPO_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Show project initialization and native drift."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    root = project_root(repo)
    scope = project_scope_root(root)
    rows: list[dict[str, Any]] = []
    # Rendering and config parsing happen here, so failures must surface as the
    # documented `error: ...` exit rather than a traceback.
    with command_boundary():
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
