"""Share adapter selection, output modes, JSON conversion, and CLI failures.

Global, project, and shared command groups use these helpers to keep quiet,
Rich, and machine-readable output behavior consistent.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import typer
from rich.console import Console

from ..agents.base import AgentAdapter
from ..agents.registry import registry
from ..core.manager import OperationResult

console = Console()


def options(ctx: typer.Context) -> dict[str, bool]:
    """Return normalized quiet and JSON flags from the root Typer context."""
    root = ctx.find_root()
    return root.obj or {"quiet": False, "json": False}


def command_options(
    ctx: typer.Context, *, quiet: bool = False, json_output: bool = False
) -> None:
    """Allow output flags both before and after a command name.

    Raises:
        typer.BadParameter: Quiet and JSON output are both requested.
    """
    flags = options(ctx)
    final_quiet = flags["quiet"] or quiet
    final_json = flags["json"] or json_output
    if final_quiet and final_json:
        raise typer.BadParameter("--quiet and --json are mutually exclusive")
    ctx.find_root().obj = {"quiet": final_quiet, "json": final_json}


def selected(names: list[str] | None) -> list[AgentAdapter]:
    """Resolve optional adapter names into installed adapter instances."""
    try:
        return registry.select(names)
    except KeyError as exc:
        raise typer.BadParameter(str(exc).strip("'"), param_hint="--agent") from exc


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
            console.print(f"  backup: {result.backup_path}")


def fail(message: str) -> NoReturn:
    """Print a consistent error and terminate the current command."""
    console.print(f"[red]error:[/red] {message}", highlight=False)
    raise typer.Exit(1)


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
