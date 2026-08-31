"""Implement root-level diff, doctor, and version workflows.

The commands combine adapter selection with core resolution, diagnostics, and
structural diff helpers without mutating managed or native files.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Literal

import typer
from rich.table import Table

from .. import __version__
from ..core.config import parse_cli_overrides
from ..core.diff import layered_changes, unified_diff
from ..core.doctor import (
    CATEGORY_ORDER,
    CheckResult,
    check_agent,
    check_environment,
    sort_key,
)
from ..core.manager import (
    capture_adapter,
    capture_assets,
    project_root,
    resolve_config,
    scope_root,
)
from .common import (
    AGENT_HELP,
    JSON_HELP,
    QUIET_HELP,
    REPO_HELP,
    command_options,
    console,
    emit,
    fail,
    options,
    selected,
)

app = typer.Typer()


@app.command("diff")
def diff_command(
    ctx: typer.Context,
    scope: Literal["global", "local"] = typer.Option("local", "--scope"),
    agent: list[str] | None = typer.Option(
        None, "--agent", "-a", help=AGENT_HELP
    ),
    set_value: list[str] | None = typer.Option(
        None, "--set", help="Override dotted KEY=VALUE."
    ),
    repo: Path = typer.Option(Path.cwd(), "--repo", help=REPO_HELP),
    check: bool = typer.Option(False, "--check", help="Exit 2 when drift exists."),
    write: bool = typer.Option(
        False,
        "--write",
        help=(
            "Capture native config drift into managed source, and hand-edited"
            " hooks/skills into their packaged source file."
        ),
    ),
    show_all: bool = typer.Option(
        False,
        "--all",
        help="Include the packaged defaults layer in the key table.",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Show layered key changes and rendered-vs-native drift."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    root = project_root(repo)
    try:
        overrides = parse_cli_overrides(set_value or [])
        records: list[dict[str, Any]] = []
        drift = False
        for adapter in selected(agent):
            captured = capture_adapter(adapter, scope, root) if write else None
            captured_assets = capture_assets(adapter, scope, root) if write else []
            merged, layers = resolve_config(adapter, scope, root, overrides)
            artifact_diffs: list[dict[str, Any]] = []
            for artifact in adapter.artifacts(scope):
                native = adapter.native_path(scope, root, artifact)
                if artifact.seed_only and native.is_file():
                    # Seeded once, then owned by the repo: divergence is expected.
                    continue
                expected = adapter.render_artifact(artifact, merged.config, scope)
                if isinstance(expected, bytes):
                    try:
                        expected_text = expected.decode("utf-8")
                    except UnicodeDecodeError:
                        text_diff = (
                            f"binary artifact differs: {native}"
                            if not native.is_file() or native.read_bytes() != expected
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
                        native.read_text(encoding="utf-8") if native.is_file() else ""
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
                        str(item["diff"]) for item in artifact_diffs if item["diff"]
                    ),
                    "capture": (
                        {
                            "changed": captured.changed,
                            "source": str(
                                scope_root(scope, root) / adapter.name / "config.toml"
                            ),
                            "message": captured.message,
                        }
                        if captured is not None
                        else None
                    ),
                    "capture_assets": [
                        {
                            "artifact": item.artifact,
                            "native": str(item.native_path),
                            "source": str(item.rendered_path),
                            "changed": item.changed,
                            "message": item.message,
                        }
                        for item in captured_assets
                    ],
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
            _render_diff(item, scope=scope, show_all=show_all)
    if check and drift:
        raise typer.Exit(2)


_VALUE_WIDTH = 60


def _short(value: Any) -> str:
    """Render a layer value for the table, elided when it is long."""
    text = repr(value)
    return text if len(text) <= _VALUE_WIDTH else text[: _VALUE_WIDTH - 1] + "…"


def _render_diff(item: dict[str, Any], *, scope: str, show_all: bool) -> None:
    """Print one agent's capture summary, overriding keys, and per-file drift."""
    console.print(f"[bold]{item['agent']}[/bold] ({scope})")
    if item["capture"] is not None and item["capture"]["changed"]:
        console.print(f"Captured config → {item['capture']['source']}")
    elif item["capture"] is not None:
        console.print(f"[dim]Nothing to capture: {item['capture']['message']}.[/dim]")
    for asset in item["capture_assets"]:
        console.print(
            f"Captured {asset['artifact']} ({asset['message']}) → {asset['source']}"
        )
    if item["capture"] is not None and (
        item["capture"]["changed"] or any(a["changed"] for a in item["capture_assets"])
    ):
        rerender = "global apply" if scope == "global" else "project update"
        console.print(
            f"[dim]Run `agentkit {rerender}` to re-render the captured values.[/dim]"
        )

    changes = item["layers"]
    shown = changes if show_all else [c for c in changes if c["layer"] != "defaults"]
    if shown:
        table = Table("Key", "Layer", "Before", "After", title="Configuration layers")
        table.title_justify = "left"
        for change in shown:
            table.add_row(
                str(change["path"]),
                str(change["layer"]),
                _short(change["before"]),
                _short(change["after"]),
            )
        console.print(table)
    else:
        console.print("[dim]No layers override the packaged defaults.[/dim]")
    hidden = len(changes) - len(shown)
    if hidden:
        console.print(
            f"[dim]{hidden} keys from packaged defaults (--all to show).[/dim]"
        )

    drifted = [artifact for artifact in item["artifacts"] if artifact["drift"]]
    if not drifted:
        console.print(
            f"[green]No drift: {len(item['artifacts'])} checked artifacts match "
            "the rendered configuration.[/green]"
        )
        return
    console.print(
        f"[magenta]{len(drifted)} of {len(item['artifacts'])} checked artifacts "
        "drifted from the rendered configuration.[/magenta]"
    )
    for artifact in drifted:
        console.print(f"[bold]{artifact['artifact']}[/bold] → {artifact['native']}")
        console.print(str(artifact["diff"]), markup=False, highlight=False)


@app.command("doctor")
def doctor_command(
    ctx: typer.Context,
    scope: Literal["global", "local"] = typer.Option("local", "--scope"),
    agent: list[str] | None = typer.Option(
        None, "--agent", "-a", help=AGENT_HELP
    ),
    repo: Path = typer.Option(Path.cwd(), "--repo", help=REPO_HELP),
    check: bool = typer.Option(False, "--check", help="Exit 2 when drift exists."),
    show_all: bool = typer.Option(False, "--all", help="Include checks that passed."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Validate schemas, templates, paths, state, binaries, and drift."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    root = project_root(repo)
    results: list[CheckResult] = []
    try:
        scope_dir = scope_root(scope, root)
        for adapter in selected(agent):
            results.extend(check_agent(adapter, scope, root, scope_dir))
        results.extend(check_environment(scope, root, scope_dir))
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
        _render_doctor(results, show_all=show_all)
    if any(item.status == "error" for item in results):
        raise typer.Exit(1)
    if check and any(item.status == "drift" for item in results):
        raise typer.Exit(2)


_STATUS_COLORS = {
    "ok": "green",
    "warning": "yellow",
    "error": "red",
    "drift": "magenta",
}


def _render_doctor(results: list[CheckResult], *, show_all: bool) -> None:
    """Print a per-agent summary, then one table per category, severity first."""
    for agent in sorted({item.agent for item in results if item.agent}):
        counts = Counter(item.status for item in results if item.agent == agent)
        parts = [
            f"[{_STATUS_COLORS[status]}]{counts[status]} {status}[/{_STATUS_COLORS[status]}]"
            for status in ("error", "drift", "warning", "ok")
            if counts[status]
        ]
        console.print(f"[bold]{agent}[/bold]  " + " · ".join(parts))

    shown = [item for item in results if show_all or item.status != "ok"]
    for category in CATEGORY_ORDER:
        rows = sorted(
            (item for item in shown if item.category == category), key=sort_key
        )
        if not rows:
            continue
        table = Table("Status", "Agent", "Check", "Message", title=category)
        table.title_justify = "left"
        for item in rows:
            color = _STATUS_COLORS[item.status]
            table.add_row(
                f"[{color}]{item.status}[/{color}]",
                item.agent or "-",
                item.check,
                item.message,
            )
        console.print(table)

    passed = sum(1 for item in results if item.status == "ok")
    if not shown:
        console.print(f"[green]All {passed} checks passed.[/green]")
    elif not show_all and passed:
        console.print(f"[dim]{passed} checks passed (--all to show).[/dim]")


@app.command("version")
def version_command(
    ctx: typer.Context,
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
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
