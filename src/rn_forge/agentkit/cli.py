"""Define agentkit's complete command-line surface.

Every Typer registration lives here: the root callback, the `global`/`project`/`self`
sub-apps, and the root-level commands, with every option name, default, and help string
inline. Each command function constructs a command object from the Typer context and
calls the matching method — the command classes in `commands/` hold all the logic.
Adapter `cli_extension` mounting and its per-plugin isolation are unrelated to this
surface and stay exactly as they were.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

import typer

from .agents.registry import registry
from .commands.base import (
    AGENT_HELP,
    DRY_RUN_HELP,
    JSON_HELP,
    QUIET_HELP,
    REPO_HELP,
    fail,
    set_json_mode,
)
from .commands.global_command import GlobalCommand
from .commands.project_command import ProjectCommand
from .commands.root_command import RootCommand
from .commands.self_command import SelfCommand
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


global_app = typer.Typer(
    help="Manage user-wide agent configuration.", no_args_is_help=True
)
project_app = typer.Typer(
    help="Manage repository-local agent configuration.", no_args_is_help=True
)
self_app = typer.Typer()


@global_app.command("apply")
def global_apply(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
    set_value: list[str] | None = typer.Option(
        None, "--set", help="Override dotted KEY=VALUE."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help=DRY_RUN_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Render and sync global configuration."""
    GlobalCommand(ctx, quiet=quiet, json_output=json_output).apply(
        agent, set_value, dry_run
    )


@global_app.command("sync")
def global_sync(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
    dry_run: bool = typer.Option(False, "--dry-run", help=DRY_RUN_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Re-sync staged global files without rendering."""
    GlobalCommand(ctx, quiet=quiet, json_output=json_output).sync(agent, dry_run)


@global_app.command("reset")
def global_reset(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    dry_run: bool = typer.Option(False, "--dry-run", help=DRY_RUN_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Back up and restore global configuration to built-in defaults."""
    GlobalCommand(ctx, quiet=quiet, json_output=json_output).reset(agent, yes, dry_run)


@global_app.command("list")
def global_list(
    ctx: typer.Context,
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """List managed adapters and their global status."""
    GlobalCommand(ctx, quiet=quiet, json_output=json_output).list()


@project_app.command("init")
def project_init(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
    repo: Path = typer.Option(Path.cwd(), "--repo", help=REPO_HELP),
    dry_run: bool = typer.Option(False, "--dry-run", help=DRY_RUN_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Scaffold, render, and sync rn-forge agentkit in a repository."""
    ProjectCommand(ctx, quiet=quiet, json_output=json_output).init(agent, repo, dry_run)


@project_app.command("update")
def project_update(
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
    ProjectCommand(ctx, quiet=quiet, json_output=json_output).update(
        agent, set_value, repo, dry_run
    )


@project_app.command("status")
def project_status(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
    repo: Path = typer.Option(Path.cwd(), "--repo", help=REPO_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Show project initialization and native drift."""
    ProjectCommand(ctx, quiet=quiet, json_output=json_output).status(agent, repo)


@project_app.command("remove")
def project_remove(
    ctx: typer.Context,
    agent: list[str] | None = typer.Option(None, "--agent", "-a", help=AGENT_HELP),
    repo: Path = typer.Option(Path.cwd(), "--repo", help=REPO_HELP),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
    dry_run: bool = typer.Option(False, "--dry-run", help=DRY_RUN_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Undo `project init`/`update`: strip hook wiring, then this repo's working data.

    The repository-local counterpart to `agentkit uninstall`: removes agentkit's hook
    registrations from each adapter's repository-local native config (Codex's
    `.codex/hooks.json`; Claude's `.claude/settings.local.json` keeps its `permissions`
    block, only losing the `hooks` key) without touching anything else, then deletes
    repository-local hook-manifest files agentkit wrote. Seed files (`CLAUDE.md`,
    `AGENTS.md`) are never touched — they are repository-owned, not agentkit's to
    remove.

    `<repo>/.rn-forge/agentkit/` (managed sources, rendered state, and any repository-
    local backups) and the `.gitignore` block `init` added are asked about separately,
    since removing the working-data root is the one step here nothing can undo.
    """
    ProjectCommand(ctx, quiet=quiet, json_output=json_output).remove(
        agent, repo, yes, dry_run
    )


@self_app.command("upgrade")
def self_upgrade(
    ctx: typer.Context,
    archive: Path | None = typer.Option(
        None,
        "--archive",
        help=(
            "Install from a local source tarball instead of downloading the "
            "latest release. May move to an older version than what's "
            "installed — that's treated as installing that version, not an "
            "upgrade."
        ),
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Install the latest agentkit release, or a local --archive, without applying
    config."""
    SelfCommand(ctx, quiet=quiet, json_output=json_output).upgrade(archive, quiet)


@self_app.command("cleanup")
def self_cleanup(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Remove every installed agentkit version except the one `current` points to."""
    SelfCommand(ctx, quiet=quiet, json_output=json_output).cleanup(yes, quiet)


@self_app.command("uninstall")
def self_uninstall(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
    dry_run: bool = typer.Option(False, "--dry-run", help=DRY_RUN_HELP),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Undo the global install: strip hook wiring, remove owned files, then agentkit.

    Removes agentkit's hook registrations from each adapter's native global config
    (Claude's `~/.claude/settings.json`, Codex's `~/.codex/hooks.json`) — leaving the
    rest, like permission grants and output style, untouched — deletes the skill files
    agentkit wrote under `~/.claude` and `~/.codex`, then removes the installed versions
    under `$RNF_HOME/agentkit/` and the `agentkit` command itself.

    `$RNF_HOME/share/agentkit` (managed sources, rendered state, and every backup
    agentkit has ever taken) is asked about separately, since removing it is the one
    step here nothing can undo. Repository-local installs from `agentkit project init`
    are untouched — run `agentkit project remove` in each one.
    """
    SelfCommand(ctx, quiet=quiet, json_output=json_output).uninstall(yes, dry_run)


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
    RootCommand(ctx, quiet=quiet, json_output=json_output).diff(
        scope, agent, set_value, repo, check, write, promote_defaults, show_all
    )


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
    RootCommand(ctx, quiet=quiet, json_output=json_output).doctor(
        scope, agent, repo, check, show_all
    )


@app.command("version")
def version_command(
    ctx: typer.Context,
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Show agentkit and adapter versions."""
    RootCommand(ctx, quiet=quiet, json_output=json_output).version()


app.add_typer(global_app, name="global")
app.add_typer(project_app, name="project")
app.add_typer(self_app)

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
