import json
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rn_forge.agentkit import __version__
from rn_forge.agentkit.cli import app
from rn_forge.agentkit.commands import self_command

runner = CliRunner()


def _fake_install(rnf: Path) -> None:
    product_home = rnf / "agentkit"
    (product_home / "v1.0.0").mkdir(parents=True)
    (product_home / "current").symlink_to("v1.0.0")
    bin_dir = rnf / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "agentkit").symlink_to(product_home / "current" / "agentkit")


def _make_archive(tmp_path: Path, version: str) -> Path:
    """Build a minimal source tarball shaped like an agentkit release checkout."""
    source_dir = tmp_path / f"agentkit-{version}"
    source_dir.mkdir()
    (source_dir / "pyproject.toml").write_text(
        f'[project]\nname = "rn-forge-agentkit"\nversion = "{version}"\n'
    )

    archive_path = tmp_path / f"agentkit-{version}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(source_dir, arcname=source_dir.name)
    return archive_path


def _stub_build_env(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Replace the real `uv sync` build with a directory stamp, offline and fast."""
    calls: list[Path] = []

    def fake_build_env(source_root: Path, env_dir: Path) -> None:
        calls.append(env_dir)
        env_dir.mkdir(parents=True)
        (env_dir / "marker").write_text(source_root.name)

    monkeypatch.setattr(self_command, "_build_env", fake_build_env)
    return calls


def test_upgrade_archive_installs_new_version(
    isolated_env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, rnf, _ = isolated_env
    _stub_build_env(monkeypatch)
    archive = _make_archive(tmp_path, "9.9.9")

    result = runner.invoke(app, ["--json", "upgrade", "--archive", str(archive)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "status": "installed",
        "version": "9.9.9",
        "previous": __version__,
    }

    product_home = rnf / "agentkit"
    assert (product_home / "v9.9.9" / "marker").read_text() == "agentkit-9.9.9"
    assert (product_home / "current").resolve() == (product_home / "v9.9.9").resolve()


def test_upgrade_archive_already_current_is_a_noop(
    isolated_env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, _ = isolated_env

    def fail_if_called(source_root: Path, env_dir: Path) -> None:
        raise AssertionError("must not build when already on the resolved version")

    monkeypatch.setattr(self_command, "_build_env", fail_if_called)
    archive = _make_archive(tmp_path, __version__)

    result = runner.invoke(app, ["--json", "upgrade", "--archive", str(archive)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "status": "already-current",
        "version": __version__,
    }


def test_upgrade_archive_not_found(isolated_env, tmp_path: Path) -> None:
    _, _, _ = isolated_env
    result = runner.invoke(
        app, ["--json", "upgrade", "--archive", str(tmp_path / "nope.tar.gz")]
    )
    assert result.exit_code != 0
    assert "archive not found" in json.loads(result.stdout)["error"]["message"]


def test_cleanup_removes_old_versions_keeps_current(
    isolated_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, rnf, _ = isolated_env
    product_home = rnf / "agentkit"
    for name in ("v1.0.0", "v1.1.0", "v2.0.0"):
        (product_home / name).mkdir(parents=True)
    (product_home / "current").symlink_to("v2.0.0")

    result = runner.invoke(app, ["--json", "cleanup", "--yes"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert sorted(payload["removed"]) == ["v1.0.0", "v1.1.0"]
    assert payload["kept"] == "v2.0.0"

    remaining = sorted(p.name for p in product_home.iterdir())
    assert remaining == ["current", "v2.0.0"]


def test_cleanup_nothing_to_remove(isolated_env) -> None:
    _, rnf, _ = isolated_env
    product_home = rnf / "agentkit"
    (product_home / "v1.0.0").mkdir(parents=True)
    (product_home / "current").symlink_to("v1.0.0")

    result = runner.invoke(app, ["--json", "cleanup", "--yes"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"removed": []}


def test_cleanup_without_current_install_fails(isolated_env) -> None:
    _, _, _ = isolated_env
    result = runner.invoke(app, ["--json", "cleanup", "--yes"])
    assert result.exit_code != 0
    assert "no current install found" in json.loads(result.stdout)["error"]["message"]


def test_cleanup_declined_confirmation_removes_nothing(isolated_env) -> None:
    _, rnf, _ = isolated_env
    product_home = rnf / "agentkit"
    (product_home / "v1.0.0").mkdir(parents=True)
    (product_home / "v2.0.0").mkdir(parents=True)
    (product_home / "current").symlink_to("v2.0.0")

    result = runner.invoke(app, ["cleanup"], input="n\n")
    assert result.exit_code != 0
    assert (product_home / "v1.0.0").exists()


def test_uninstall_strips_hooks_removes_owned_files_and_install(isolated_env) -> None:
    home, rnf, _ = isolated_env
    _fake_install(rnf)
    applied = runner.invoke(app, ["global", "apply"])
    assert applied.exit_code == 0, applied.output

    result = runner.invoke(app, ["uninstall", "--yes"])
    assert result.exit_code == 0, result.output

    claude_settings = json.loads((home / ".claude/settings.json").read_text())
    assert "hooks" not in claude_settings
    assert claude_settings["permissions"]["deny"]
    assert not (home / ".codex/hooks.json").exists()
    assert not any((home / ".claude/skills").rglob("*"))
    assert not (rnf / "share" / "agentkit").exists()
    assert not (rnf / "agentkit").exists()
    assert not (rnf / "bin" / "agentkit").exists()


def test_uninstall_dry_run_changes_nothing(isolated_env) -> None:
    home, rnf, _ = isolated_env
    _fake_install(rnf)
    applied = runner.invoke(app, ["global", "apply"])
    assert applied.exit_code == 0, applied.output

    result = runner.invoke(app, ["uninstall", "--dry-run"])
    assert result.exit_code == 0, result.output

    assert "hooks" in json.loads((home / ".claude/settings.json").read_text())
    assert (home / ".codex/hooks.json").exists()
    assert (rnf / "share" / "agentkit").exists()
    assert (rnf / "agentkit" / "v1.0.0").exists()


def test_uninstall_declining_share_removal_keeps_backups_and_sources(
    isolated_env,
) -> None:
    home, rnf, _ = isolated_env
    _fake_install(rnf)
    applied = runner.invoke(app, ["global", "apply"])
    assert applied.exit_code == 0, applied.output

    result = runner.invoke(app, ["uninstall"], input="y\nn\n")
    assert result.exit_code == 0, result.output

    assert "hooks" not in json.loads((home / ".claude/settings.json").read_text())
    assert (rnf / "share" / "agentkit").exists()
    assert not (rnf / "agentkit").exists()
