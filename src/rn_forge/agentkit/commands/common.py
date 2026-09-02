"""Share adapter selection, output modes, JSON conversion, and CLI failures.

Global, project, and shared command groups use these helpers to keep quiet, Rich, and
machine-readable output behavior consistent.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import typer
from rich.console import Console

from ..agents.base import AgentAdapter
from ..agents.registry import registry
from ..core.operations import OperationResult

console = Console()
error_console = Console(stderr=True)
"""Human-readable diagnostics go to stderr, never to a caller's parsed stdout."""

_json_mode = False
"""Mirror of the active --json flag for helpers that receive no Typer context."""

AGENT_HELP = "Agent(s); default is all."
DRY_RUN_HELP = "Show changes without writing."
QUIET_HELP = "Suppress output."
JSON_HELP = "Emit JSON."
REPO_HELP = "Repository directory."


def set_json_mode(value: bool) -> None:
    """Set the module-wide JSON mode used by :func:`fail` before a Typer context exists.

    The root callback resolves ``--json`` before any command-level context or
    ``command_options`` call exists, but a root-level parameter conflict must still fail
    through the JSON error contract when ``--json`` was passed.
    """
    global _json_mode
    _json_mode = value


def options(ctx: typer.Context) -> dict[str, bool]:
    """Return normalized quiet and JSON flags from the root Typer context."""
    root = ctx.find_root()
    return root.obj or {"quiet": False, "json": False}


def command_options(
    ctx: typer.Context, *, quiet: bool = False, json_output: bool = False
) -> None:
    """Allow output flags both before and after a command name.

    A conflict is reported through :func:`fail` rather than raised as
    ``typer.BadParameter`` so that ``--json`` still gets a JSON error object instead of
    Typer's human usage text — even though the conflict is what makes the requested mode
    ambiguous, ``--json`` alone is enough to commit to the JSON error contract.
    """
    flags = options(ctx)
    final_quiet = flags["quiet"] or quiet
    final_json = flags["json"] or json_output
    global _json_mode
    _json_mode = final_json
    if final_quiet and final_json:
        fail("--quiet and --json are mutually exclusive")
    ctx.find_root().obj = {"quiet": final_quiet, "json": final_json}


def selected(names: list[str] | None) -> list[AgentAdapter]:
    """Resolve optional adapter names into installed adapter instances."""
    try:
        return registry.select(names)
    except KeyError as exc:
        fail(str(exc).strip("'"))


def emit(ctx: typer.Context, value: Any, *, quiet_text: str | None = None) -> None:
    """Emit a value according to the active Rich, quiet, or JSON mode."""
    flags = options(ctx)
    if flags["json"]:
        typer.echo(json.dumps(_jsonable(value), indent=2, sort_keys=True))
    elif flags["quiet"]:
        if quiet_text:
            typer.echo(quiet_text)
    elif isinstance(value, str):
        console.print(value)
    else:
        console.print(value)


def emit_operations(ctx: typer.Context, results: list[OperationResult]) -> None:
    """Emit per-artifact operation results for human or JSON consumers."""
    if options(ctx)["json"]:
        emit(ctx, results)
        return
    if options(ctx)["quiet"]:
        return
    for result in results:
        status = "changed" if result.changed else "unchanged"
        dry = " (dry-run)" if result.message == "dry-run" else ""
        console.print(
            f"[bold]{result.agent}[/bold]/{result.artifact}: "
            f"{result.action} {status}{dry} → {result.native_path}"
        )
        if result.diff and result.message == "dry-run":
            console.print(result.diff, markup=False)
        if result.backup_path:
            if result.message == "drift detected":
                console.print(
                    "  [yellow]warning:[/yellow] native file changed outside "
                    f"agentkit since last apply — backed up to {result.backup_path}"
                )
            else:
                console.print(f"  backup: {result.backup_path}")


def fail(message: str) -> NoReturn:
    """Report a command failure and terminate, honouring the output contract.

    Under ``--json`` the only thing on stdout is a JSON document, so an error is emitted
    as a stable error object there rather than as styled prose that would break a parser
    mid-stream. Otherwise the diagnostic goes to stderr, leaving stdout for the
    command's actual output.
    """
    if _json_mode:
        typer.echo(json.dumps({"error": {"message": message}}, indent=2))
    else:
        error_console.print(f"[red]error:[/red] {message}", highlight=False)
    raise typer.Exit(1)


@contextmanager
def command_boundary() -> Generator[None]:
    """Normalize expected domain failures into the documented CLI error contract.

    Rendering, config parsing, plugin loading, and filesystem access all raise ordinary
    exceptions. Without a boundary a broken template or an unreadable config surfaces as
    a traceback instead of ``error: ...`` and exit 1.
    """
    try:
        yield
    except (OSError, ValueError, KeyError) as exc:
        fail(str(exc))


def warn_if_jq_missing() -> None:
    """Warn before installing assets whose safety hooks require jq."""
    if shutil.which("jq") is None:
        typer.echo(
            "WARNING: jq is not installed; agentkit safety hooks require it. "
            "Install jq before using the managed agent configuration.",
            err=True,
        )


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        mapping = cast(dict[Any, Any], value)
        return {str(key): _jsonable(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(list[Any] | tuple[Any, ...], value)
        return [_jsonable(item) for item in sequence]
    if isinstance(value, Path):
        return str(value)
    return value
