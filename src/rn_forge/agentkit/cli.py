"""Create the root Typer application and mount agentkit command groups.

The dispatcher combines built-in global, project, and shared commands with any
adapter-specific Typer extensions exposed by the adapter registry.
"""

from __future__ import annotations

import typer

from .agents.registry import registry
from .commands import global_cmds, project_cmds, shared_cmds

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
    if quiet and json_output:
        raise typer.BadParameter("--quiet and --json are mutually exclusive")
    ctx.obj = {"quiet": quiet, "json": json_output}


app.add_typer(global_cmds.app, name="global")
app.add_typer(project_cmds.app, name="project")
app.add_typer(shared_cmds.app)

for adapter in registry.discover():
    if adapter.cli_extension is not None:
        app.add_typer(adapter.cli_extension, name=adapter.name)
