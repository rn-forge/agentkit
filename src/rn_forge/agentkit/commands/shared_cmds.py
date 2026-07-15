"""Implement root-level diff, doctor, and version workflows.

The commands combine adapter selection with core resolution, diagnostics, and
structural diff helpers without mutating managed or native files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import typer
from rich.table import Table

from .. import __version__
from ..core.config import parse_cli_overrides
from ..core.diff import layered_changes, unified_diff
from ..core.doctor import CheckResult, check_agent
from ..core.manager import project_root, resolve_config, scope_root
from .common import command_options, console, emit, fail, options, selected

app = typer.Typer()


@app.command("diff")
def diff_command(
    ctx: typer.Context,
    scope: Literal["global", "local"] = typer.Option("local", "--scope"),
    agent: list[str] | None = typer.Option(
        None, "--agent", "-a", help="Agent(s); default is all."
    ),
    set_value: list[str] | None = typer.Option(
        None, "--set", help="Override dotted KEY=VALUE."
    ),
    repo: Path = typer.Option(Path.cwd(), "--repo", help="Repository directory."),
    check: bool = typer.Option(False, "--check", help="Exit 2 when drift exists."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show layered key changes and rendered-vs-native drift."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    root = project_root(repo)
    try:
        overrides = parse_cli_overrides(set_value or [])
        records: list[dict[str, Any]] = []
        drift = False
        for adapter in selected(agent):
            merged, layers = resolve_config(adapter, scope, root, overrides)
            artifact_diffs: list[dict[str, Any]] = []
            for artifact in adapter.artifacts(scope):
                expected = adapter.render_artifact(artifact, merged.config, scope)
                native = adapter.native_path(scope, root, artifact)
                if isinstance(expected, bytes):
                    try:
                        expected_text = expected.decode("utf-8")
                    except UnicodeDecodeError:
                        text_diff = (
                            f"binary artifact differs: {native}"
                            if not native.is_file()
                            or native.read_bytes() != expected
                            else ""
                        )
                    else:
                        actual = (
                            native.read_text(encoding="utf-8")
                            if native.is_file()
                            else ""
                        )
                        text_diff = unified_diff(
                            expected_text,
                            actual,
                            expected_name=f"merged/rendered:{artifact.key}",
                            actual_name=str(native),
                        )
                else:
                    actual = (
                        native.read_text(encoding="utf-8")
                        if native.is_file()
                        else ""
                    )
                    text_diff = unified_diff(
                        expected,
                        actual,
                        expected_name=f"merged/rendered:{artifact.key}",
                        actual_name=str(native),
                    )
                artifact_diffs.append(
                    {
                        "artifact": artifact.key,
                        "native": str(native),
                        "drift": bool(text_diff),
                        "diff": text_diff,
                    }
                )
            has_drift = any(item["drift"] for item in artifact_diffs)
            drift = drift or has_drift
            records.append(
                {
                    "agent": adapter.name,
                    "scope": scope,
                    "provenance": merged.provenance,
                    "layers": [
                        {
                            "path": change.path,
                            "layer": change.layer,
                            "before": change.before,
                            "after": change.after,
                        }
                        for change in layered_changes(layers)
                    ],
                    "artifacts": artifact_diffs,
                    "drift": has_drift,
                    "diff": "\n".join(
                        str(item["diff"])
                        for item in artifact_diffs
                        if item["diff"]
                    ),
                }
            )
    except (OSError, ValueError) as exc:
        fail(str(exc))

    if options(ctx)["json"]:
        emit(ctx, records)
    elif options(ctx)["quiet"]:
        typer.echo("\n".join(item["agent"] for item in records if item["drift"]))
    else:
        for item in records:
            console.print(f"[bold]{item['agent']}[/bold] ({scope})")
            table = Table("Key", "Layer", "Before", "After")
            for change in item["layers"]:
                table.add_row(
                    str(change["path"]),
                    str(change["layer"]),
                    repr(change["before"]),
                    repr(change["after"]),
                )
            console.print(table)
            if item["diff"]:
                console.print(item["diff"], markup=False)
            else:
                console.print("No rendered/native drift.")
    if check and drift:
        raise typer.Exit(2)


@app.command("doctor")
def doctor_command(
    ctx: typer.Context,
    scope: Literal["global", "local"] = typer.Option("local", "--scope"),
    agent: list[str] | None = typer.Option(
        None, "--agent", "-a", help="Agent(s); default is all."
    ),
    repo: Path = typer.Option(Path.cwd(), "--repo", help="Repository directory."),
    check: bool = typer.Option(False, "--check", help="Exit 2 when drift exists."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Validate schemas, templates, paths, state, binaries, and drift."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    root = project_root(repo)
    results: list[CheckResult] = []
    try:
        for adapter in selected(agent):
            results.extend(check_agent(adapter, scope, root, scope_root(scope, root)))
    except (OSError, ValueError) as exc:
        fail(str(exc))
    if options(ctx)["json"]:
        emit(ctx, results)
    elif options(ctx)["quiet"]:
        typer.echo(
            "\n".join(
                f"{item.agent}:{item.status}:{item.check}"
                for item in results
                if item.status != "ok"
            )
        )
    else:
        table = Table("Status", "Agent", "Check", "Message")
        colors = {
            "ok": "green",
            "warning": "yellow",
            "error": "red",
            "drift": "magenta",
        }
        for item in results:
            table.add_row(
                f"[{colors[item.status]}]{item.status}[/{colors[item.status]}]",
                item.agent,
                item.check,
                item.message,
            )
        console.print(table)
    if any(item.status == "error" for item in results):
        raise typer.Exit(1)
    if check and any(item.status == "drift" for item in results):
        raise typer.Exit(2)


@app.command("version")
def version_command(
    ctx: typer.Context,
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show agentkit and adapter versions."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    adapter_versions: dict[str, str] = {
        adapter.name: adapter.version for adapter in selected(None)
    }
    data: dict[str, Any] = {
        "agentkit": __version__,
        "adapters": adapter_versions,
    }
    if options(ctx)["json"]:
        emit(ctx, data)
    elif options(ctx)["quiet"]:
        typer.echo(__version__)
    else:
        console.print(f"agentkit {__version__}")
        for name, adapter_version in adapter_versions.items():
            console.print(f"  {name}: {adapter_version}")
