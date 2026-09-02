"""Implement `agentkit upgrade`, `agentkit cleanup`, and `agentkit uninstall`.

The first two manage agentkit's own versioned install under `$RNF_HOME/agentkit/` —
fetching and swapping in a new release (or a local `--archive`) and pruning superseded
versions — without touching managed or native agent config; see `docs/specs/initial.md`
§8 for why that split is deliberate. `uninstall` is the deliberate exception: undoing an
install means undoing what `global apply` put in place first, then removing the install
itself.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import typer

from .. import __version__
from ..core.operations import (
    OperationResult,
    remove_owned_artifacts,
    strip_native_hooks,
)
from ..core.paths import global_root, project_root, rnf_home
from .common import (
    DRY_RUN_HELP,
    JSON_HELP,
    QUIET_HELP,
    command_boundary,
    command_options,
    console,
    emit,
    emit_operations,
    fail,
    options,
    selected,
)

app = typer.Typer()

GITHUB_REPO = "rn-forge/agentkit"
_INSTALL_LOCK_TIMEOUT = 30.0
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _product_home() -> Path:
    return rnf_home() / "agentkit"


def _current_version_dir(product_home: Path) -> str | None:
    current = product_home / "current"
    if not current.is_symlink():
        return None
    return os.readlink(current)


def _read_version(pyproject: Path) -> str:
    match = _VERSION_RE.search(pyproject.read_text())
    if not match:
        fail(f"could not read version from {pyproject}")
    return match.group(1)


def _resolve_latest_tag() -> str:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    with urllib.request.urlopen(url) as response:  # noqa: S310 - fixed https github.com host
        data = json.load(response)
    tag = data.get("tag_name")
    if not tag:
        fail(f"could not resolve latest release tag for {GITHUB_REPO}")
    return tag


def _download_tarball(tag: str, dest: Path) -> None:
    url = f"https://github.com/{GITHUB_REPO}/archive/refs/tags/{tag}.tar.gz"
    urllib.request.urlretrieve(url, dest)  # noqa: S310 - fixed https github.com host


def _extract_source(tarball: Path, extract_dir: Path) -> Path:
    with tarfile.open(tarball, "r:gz") as archive:
        archive.extractall(extract_dir, filter="data")
    entries = [item for item in extract_dir.iterdir() if item.is_dir()]
    if not entries:
        fail("extracted archive was empty")
    return entries[0]


class _InstallLock:
    """Portable mkdir-based lock — no flock assumption, same as install.sh's peer."""

    def __init__(self, lock_dir: Path, timeout: float = _INSTALL_LOCK_TIMEOUT) -> None:
        self._lock_dir = lock_dir
        self._timeout = timeout

    def __enter__(self) -> "_InstallLock":
        waited = 0.0
        announced = False
        while True:
            try:
                self._lock_dir.mkdir(parents=False)
                return self
            except FileExistsError:
                if waited >= self._timeout:
                    fail(f"could not acquire install lock {self._lock_dir}")
                if not announced:
                    console.print(f"waiting for install lock {self._lock_dir} ...")
                    announced = True
                time.sleep(1)
                waited += 1

    def __exit__(self, *exc_info: object) -> None:
        shutil.rmtree(self._lock_dir, ignore_errors=True)


def _build_env(source_root: Path, env_dir: Path) -> None:
    """Build a `uv`-managed environment for `source_root` at `env_dir`.

    Kept as its own seam so tests can stub the (slow, network-touching) real build
    without exercising the atomic-swap and locking logic around it.
    """
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(env_dir)
    subprocess.run(
        ["uv", "sync", "--frozen", "--no-dev", "--no-editable"],
        cwd=source_root,
        env=env,
        check=True,
    )


def _install_version(source_root: Path, product_home: Path, version: str) -> Path:
    """Build `v<version>/` in place.

    Unlike `current`, a version directory is never observed until `current` is repointed
    at it, so building it directly (rather than staging elsewhere and renaming in) is
    already safe — and necessary: `uv sync` bakes the target path into console-script
    shebangs and activation scripts, so a build-then-rename would silently produce a
    venv whose scripts point at a path that no longer exists.
    """
    target = product_home / f"v{version}"
    shutil.rmtree(target, ignore_errors=True)
    try:
        _build_env(source_root, target)
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(target, ignore_errors=True)
        fail(f"build failed for v{version}: {exc}")
    return target


def _flip_current(product_home: Path, target: Path) -> None:
    tmp_link = product_home / f".current.tmp.{os.getpid()}"
    tmp_link.symlink_to(target.name)
    tmp_link.replace(product_home / "current")


@app.command("upgrade")
def upgrade_command(
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
    command_options(ctx, quiet=quiet, json_output=json_output)
    product_home = _product_home()
    product_home.mkdir(parents=True, exist_ok=True)
    current_version = __version__

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tarball = tmp_path / "agentkit.tar.gz"
        if archive is not None:
            if not archive.is_file():
                fail(f"archive not found: {archive}")
            shutil.copy(archive, tarball)
        else:
            _download_tarball(_resolve_latest_tag(), tarball)

        source_root = _extract_source(tarball, tmp_path / "extracted")
        version = _read_version(source_root / "pyproject.toml")

        if version == current_version:
            _report(
                ctx,
                {"status": "already-current", "version": version},
                f"agentkit v{version} is already installed.",
            )
            return

        verb = "Installing" if archive is not None else "Upgrading to"
        if not quiet and not options(ctx)["json"]:
            console.print(
                f"{verb} agentkit v{version} (current: v{current_version}) ..."
            )

        with _InstallLock(product_home / ".install.lock"):
            target = _install_version(source_root, product_home, version)
            _flip_current(product_home, target)

    _report(
        ctx,
        {"status": "installed", "version": version, "previous": current_version},
        f"agentkit v{version} installed. Configuration was not applied — run "
        "'agentkit global apply' (and 'agentkit project update' per repo) to "
        "pick up any changes.",
    )


@app.command("cleanup")
def cleanup_command(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=QUIET_HELP),
    json_output: bool = typer.Option(False, "--json", help=JSON_HELP),
) -> None:
    """Remove every installed agentkit version except the one `current` points to."""
    command_options(ctx, quiet=quiet, json_output=json_output)
    product_home = _product_home()
    current_name = _current_version_dir(product_home)
    if current_name is None:
        fail(f"no current install found at {product_home / 'current'}")

    to_remove = sorted(
        item
        for item in product_home.glob("v*")
        if item.is_dir() and item.name != current_name
    )
    if not to_remove:
        _report(
            ctx,
            {"removed": []},
            f"nothing to clean up — only {current_name} is installed.",
        )
        return

    if not options(ctx)["json"] and not quiet:
        for item in to_remove:
            console.print(f"  {item.name}")
    if not yes and not typer.confirm(
        f"Remove {len(to_remove)} old version(s) from {product_home}?"
    ):
        raise typer.Abort()

    for item in to_remove:
        shutil.rmtree(item)

    _report(
        ctx,
        {"removed": [item.name for item in to_remove], "kept": current_name},
        f"removed {len(to_remove)} old version(s), kept {current_name}.",
    )


@app.command("uninstall")
def uninstall_command(
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
    command_options(ctx, quiet=quiet, json_output=json_output)
    adapters = selected(None)
    repo_root = project_root()
    share_root = global_root()
    product_home = _product_home()
    bin_link = rnf_home() / "bin" / "agentkit"

    if not dry_run and not yes:
        names = ", ".join(item.name for item in adapters)
        if not typer.confirm(
            f"Remove agentkit's hook registrations and owned files for {names}?"
        ):
            raise typer.Abort()

    results: list[OperationResult] = []
    with command_boundary():
        for adapter in adapters:
            results.append(
                strip_native_hooks(adapter, "global", repo_root, dry_run=dry_run)
            )
            results.extend(
                remove_owned_artifacts(adapter, "global", repo_root, dry_run=dry_run)
            )

    if not share_root.is_dir():
        remove_share, share_message = False, "already absent"
    elif dry_run:
        remove_share, share_message = True, "dry-run"
    elif yes or typer.confirm(
        f"Also remove {share_root}? This deletes agentkit's managed sources, "
        "rendered state, and every backup it has ever taken for every repository — "
        "irreversible."
    ):
        remove_share, share_message = True, "removed"
        shutil.rmtree(share_root)
    else:
        remove_share, share_message = False, "kept — not confirmed"
    results.append(
        OperationResult(
            "agentkit",
            "share",
            "remove",
            remove_share,
            share_root,
            share_root,
            message=share_message,
        )
    )

    install_present = product_home.is_dir() or bin_link.is_symlink()
    if install_present and not dry_run:
        if product_home.is_dir():
            shutil.rmtree(product_home)
        bin_link.unlink(missing_ok=True)
    results.append(
        OperationResult(
            "agentkit",
            "install",
            "remove",
            install_present,
            product_home,
            product_home,
            message="dry-run"
            if dry_run
            else ("removed" if install_present else "already absent"),
        )
    )

    emit_operations(ctx, results)


def _report(ctx: typer.Context, data: dict[str, Any], text: str) -> None:
    if options(ctx)["json"]:
        emit(ctx, data)
    elif not options(ctx)["quiet"]:
        console.print(text)
