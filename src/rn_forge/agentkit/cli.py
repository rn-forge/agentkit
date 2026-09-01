"""Create the root Typer application and mount agentkit command groups.

The dispatcher combines built-in global, project, and shared commands with any adapter-
specific Typer extensions exposed by the adapter registry.
"""

from __future__ import annotations

import sys

import typer

from .agents.registry import registry
from .commands import global_cmds, project_cmds, self_cmds, shared_cmds
from .commands.common import fail, set_json_mode
from .core.state import start_backup_run

app = typer.Typer(
    name="agentkit",
    help="Manage layered configuration for AI coding agents.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)


@app.callback()
def root_options(
    ctx: typer.Context,
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress non-essential output."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Manage global and repository-local AI agent configuration."""
    start_backup_run()
    set_json_mode(json_output)
    if quiet and json_output:
        fail("--quiet and --json are mutually exclusive")
    ctx.obj = {"quiet": quiet, "json": json_output}


app.add_typer(global_cmds.app, name="global")
app.add_typer(project_cmds.app, name="project")
app.add_typer(shared_cmds.app)
app.add_typer(self_cmds.app)

for adapter in registry.discover():
    # A plugin's `cli_extension` runs arbitrary third-party code (a property
    # getter, or a value that is not actually a Typer app) outside the
    # isolation `registry.discover()` already gives entry-point loading and
    # construction, so it gets the same treatment: one broken extension is
    # skipped rather than allowed to break `--help` for every agent.
    try:
        extension = adapter.cli_extension
        if extension is not None:
            app.add_typer(extension, name=adapter.name)
    except Exception as exc:  # noqa: BLE001 - one plugin must not break all
        print(
            f"agentkit: skipping CLI extension for {adapter.name!r}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
