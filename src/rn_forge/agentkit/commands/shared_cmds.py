"""Implement root-level diff, doctor, and version workflows.

The commands combine adapter selection with core resolution, diagnostics, and structural
diff helpers without mutating managed or native files.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Literal

import typer
from rich.table import Column, Table

from .. import __version__
from ..agents.base import AgentAdapter
from ..core.config import parse_cli_overrides
from ..core.diff import layered_changes, unified_diff
from ..core.doctor import (
    HEALTHY,
    REPAIRABLE_BY_APPLY,
    CheckResult,
    check_agent,
    check_environment,
    sort_key,
)
from ..core.operations import (
    capture_adapter,
    capture_assets,
    capture_defaults,
    resolve_config,
)
from ..core.paths import (
    global_root,
    package_root,
    project_root,
    project_scope_root,
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
    agent: list[str] | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
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
    promote_defaults: bool = typer.Option(
        False,
        "--promote-defaults",
        help=(
            "Promote the scope's managed config.toml overrides into the packaged"
            " scope defaults, so a fresh install picks them up too. Only useful"
            " running from an editable checkout of this repo; combine with"
            " --write to promote drift captured in the same run."
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
            captured_defaults = (
                capture_defaults(adapter, scope, root) if promote_defaults else None
            )
            merged, layers = resolve_config(adapter, scope, root, overrides)
            artifact_diffs: list[dict[str, Any]] = []
            for artifact in adapter.artifacts(scope):
                native = adapter.native_path(scope, root, artifact)
                if artifact.seed_only and native.is_file():
                    # Seeded once, then owned by the repo: divergence is expected.
                    continue
                expected = adapter.render_artifact(artifact, merged.config, scope)
                text_diff = _artifact_diff(
                    expected,
                    native,
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
                    "capture_defaults": (
                        {
                            "changed": captured_defaults.changed,
                            "source": str(captured_defaults.rendered_path),
                            "message": captured_defaults.message,
                        }
                        if captured_defaults is not None
                        else None
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
            _render_diff(item, scope=scope, show_all=show_all)
    if check and drift:
        raise typer.Exit(2)


def _artifact_diff(
    expected: str | bytes, actual_path: Path, *, expected_name: str, actual_name: str
) -> str:
    """Return a unified diff between rendered content and a file on disk.

    Returns an empty string when they match, or a one-line binary-mismatch note when the
    expected content is not valid UTF-8 text.
    """
    if isinstance(expected, bytes):
        try:
            expected_text = expected.decode("utf-8")
        except UnicodeDecodeError:
            if not actual_path.is_file() or actual_path.read_bytes() != expected:
                return f"binary artifact differs: {actual_path}"
            return ""
    else:
        expected_text = expected
    actual = actual_path.read_text(encoding="utf-8") if actual_path.is_file() else ""
    return unified_diff(
        expected_text, actual, expected_name=expected_name, actual_name=actual_name
    )


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
    if item["capture_defaults"] is not None and item["capture_defaults"]["changed"]:
        console.print(f"Promoted config → {item['capture_defaults']['source']}")
    elif item["capture_defaults"] is not None:
        console.print(
            f"[dim]Nothing to promote: {item['capture_defaults']['message']}.[/dim]"
        )
    if item["capture"] is not None and (
        item["capture"]["changed"]
        or any(a["changed"] for a in item["capture_assets"])
        or (
            item["capture_defaults"] is not None and item["capture_defaults"]["changed"]
        )
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
    agent: list[str] | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
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
    adapters = selected(agent)
    try:
        scope_dir = scope_root(scope, root)
        for adapter in adapters:
            results.extend(check_agent(adapter, scope, root, scope_dir))
        results.extend(check_environment(scope, root, scope_dir))
    except (OSError, ValueError) as exc:
        fail(str(exc))
    if options(ctx)["json"]:
        emit(ctx, results)
    elif options(ctx)["quiet"]:
        typer.echo(
            "\n".join(
                f"{item.agent}:{item.severity}:{item.status}:{item.kind}"
                for item in results
                if item.status not in HEALTHY
            )
        )
    else:
        artifact_rows = _render_doctor(
            results, show_all=show_all, scope=scope, repo_root=root
        )
        if sys.stdin.isatty() and sys.stdout.isatty():
            _interactive_diff_session(
                artifact_rows, adapters, scope=scope, root=root, scope_dir=scope_dir
            )
    if any(item.severity == "error" for item in results):
        raise typer.Exit(1)
    if check and any(item.status in REPAIRABLE_BY_APPLY for item in results):
        raise typer.Exit(2)


_SEVERITY_COLORS = {"info": "green", "warning": "yellow", "error": "red"}


def _path_roots(
    scope: Literal["global", "local"], repo_root: Path
) -> list[tuple[str, Path]]:
    """Return the ``$TOKEN`` prefixes doctor abbreviates absolute paths with.

    Longest path first, because the share root lives *inside* the home or repo root and
    must win the match against it.
    """
    roots = [
        ("$PKG", package_root()),
        (
            "$SHARE",
            global_root() if scope == "global" else project_scope_root(repo_root),
        ),
        ("$HOME", Path.home()) if scope == "global" else ("$REPO", Path(repo_root)),
    ]
    return sorted(roots, key=lambda item: len(str(item[1])), reverse=True)


def _abbreviate(path: Path, roots: list[tuple[str, Path]], used: set[str]) -> str:
    """Replace a known root prefix with its token, recording which token was used.

    Nothing is elided: a path under no known root is printed in full. Factoring
    the shared prefixes out is what lets both a source and a target path fit a
    normal terminal without rich truncating either to an ellipsis.
    """
    for token, root in roots:
        if path == root or root in path.parents:
            used.add(token)
            return f"{token}/{path.relative_to(root)}"
    return str(path)


def _render_doctor(
    results: list[CheckResult],
    *,
    show_all: bool,
    scope: Literal["global", "local"],
    repo_root: Path,
) -> list[CheckResult]:
    """Print a per-agent summary, then the artifact and diagnostic tables.

    Artifact rows carry no message: ``source``, ``target``, and ``status``
    together say which two files were compared and how they differ. Rows with no
    two files to compare — schema errors, dependencies, binaries, plugins, state
    — go to the diagnostics table, where the detail is the whole point.

    Returns:
        The artifact rows in the order printed, numbered starting at 1 in the
        ``#`` column — the same numbering an interactive diff prompt indexes
        into, so what a caller can select always matches what was shown.
    """
    for agent in sorted({item.agent for item in results if item.agent}):
        owned = [item for item in results if item.agent == agent]
        counts = Counter(item.severity for item in owned if item.status not in HEALTHY)
        parts = [
            f"[{_SEVERITY_COLORS[severity]}]{counts[severity]} {severity}"
            f"[/{_SEVERITY_COLORS[severity]}]"
            for severity in ("error", "warning")
            if counts[severity]
        ]
        healthy = sum(1 for item in owned if item.status in HEALTHY)
        if healthy:
            parts.append(f"[green]{healthy} ok[/green]")
        console.print(f"[bold]{agent}[/bold]  " + " · ".join(parts))

    shown = sorted(
        (item for item in results if show_all or item.status not in HEALTHY),
        key=sort_key,
    )
    roots = _path_roots(scope, repo_root)
    used: set[str] = set()

    artifact_rows = [item for item in shown if item.target is not None]
    diagnostic_rows = [item for item in shown if item.target is None]

    # `fold` rather than the default `ellipsis`: a doctor row exists to be acted
    # on, and a path ending in "…" cannot be opened, grepped, or copied. A
    # narrow terminal wraps these cells; it never drops characters from them.
    artifacts = Table(
        "#",
        "Agent",
        "Type",
        "Status",
        "Severity",
        Column("Source", overflow="fold"),
        Column("Target", overflow="fold"),
    )
    for index, item in enumerate(artifact_rows, start=1):
        color = _SEVERITY_COLORS[item.severity]
        artifacts.add_row(
            str(index),
            item.agent or "-",
            item.kind,
            f"[{color}]{item.status}[/{color}]",
            item.severity,
            _abbreviate(item.source, roots, used) if item.source else "-",
            _abbreviate(item.target, roots, used) if item.target else "-",
        )

    diagnostics = Table(
        "Agent", "Type", "Status", "Severity", Column("Detail", overflow="fold")
    )
    for item in diagnostic_rows:
        color = _SEVERITY_COLORS[item.severity]
        diagnostics.add_row(
            item.agent or "-",
            item.kind,
            f"[{color}]{item.status}[/{color}]",
            item.severity,
            item.message,
        )

    if artifact_rows:
        # The legend is only meaningful once the rows that reference it exist,
        # so it is built during rendering and printed before the table.
        for token, root in sorted(roots):
            if token in used:
                console.print(f"[dim]{token:<7}= {root}[/dim]", soft_wrap=True)
        console.print(artifacts)
    if diagnostic_rows:
        console.print(diagnostics)

    passed = sum(1 for item in results if item.status in HEALTHY)
    if not shown:
        console.print(f"[green]All {passed} checks passed.[/green]")
    elif not show_all and passed:
        console.print(f"[dim]{passed} checks passed (--all to show).[/dim]")

    return artifact_rows


_DIFFABLE_STATUSES = frozenset({"drift", "stale"})


def _diff_for_row(
    row: CheckResult,
    adapters: list[AgentAdapter],
    *,
    scope: Literal["global", "local"],
    root: Path,
    scope_dir: Path,
) -> str:
    """Re-render one artifact and diff it against the row's target file.

    Doctor only stores hashes, not content, so a selected row's diff is recomputed on
    demand from the same adapter and artifact the check ran against — matched back by
    target path, since a ``CheckResult`` carries no direct reference to the ``Artifact``
    that produced it.
    """
    adapter = next((item for item in adapters if item.name == row.agent), None)
    if adapter is None or row.target is None:
        return ""
    merged, _ = resolve_config(adapter, scope, root)
    for artifact in adapter.artifacts(scope):
        candidates = {adapter.native_path(scope, root, artifact)}
        if artifact.root != "share" and not artifact.seed_only:
            candidates.add(adapter.rendered_path(scope_dir, scope, artifact))
        if row.target not in candidates:
            continue
        expected = adapter.render_artifact(artifact, merged.config, scope)
        return _artifact_diff(
            expected,
            row.target,
            expected_name=f"merged/rendered:{artifact.key}",
            actual_name=str(row.target),
        )
    return ""


def _interactive_diff_session(
    artifact_rows: list[CheckResult],
    adapters: list[AgentAdapter],
    *,
    scope: Literal["global", "local"],
    root: Path,
    scope_dir: Path,
) -> None:
    """Prompt for a row number from the printed table and print its diff.

    Only runs when both stdin and stdout are attached to a terminal, so a piped or
    scripted invocation never blocks waiting for input. Blank input, ``q``, Ctrl+D, or
    Ctrl+C all exit back to the shell.
    """
    if not any(row.status in _DIFFABLE_STATUSES for row in artifact_rows):
        return
    console.print(
        "\n[dim]Enter a row number to view its diff (blank or q to exit).[/dim]"
    )
    while True:
        try:
            choice = console.input("[bold]#[/bold] ").strip()
        except EOFError, KeyboardInterrupt:
            console.print()
            return
        if not choice or choice.lower() == "q":
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(artifact_rows):
            console.print(f"[red]Enter a number from 1 to {len(artifact_rows)}.[/red]")
            continue
        row = artifact_rows[int(choice) - 1]
        if row.status not in _DIFFABLE_STATUSES:
            console.print(f"[yellow]No diff for status '{row.status}'.[/yellow]")
            continue
        text = _diff_for_row(row, adapters, scope=scope, root=root, scope_dir=scope_dir)
        console.print(f"[bold]{row.agent}[/bold]/{row.kind} → {row.target}")
        if text:
            console.print(text, markup=False, highlight=False)
        else:
            console.print("[dim](no textual diff available)[/dim]")


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
