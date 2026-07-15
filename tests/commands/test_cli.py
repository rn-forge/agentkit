import json
from pathlib import Path

import tomlkit
from typer.testing import CliRunner

from rn_forge.agentkit.cli import app

runner = CliRunner()


def test_version_json() -> None:
    result = runner.invoke(app, ["--json", "version"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert set(data["adapters"]) == {"claude", "codex"}


def test_project_init_update_status(isolated_env) -> None:
    _, _, repo = isolated_env

    initialized = runner.invoke(
        app, ["project", "init", "--agent", "codex", "--repo", str(repo)]
    )
    assert initialized.exit_code == 0, initialized.output
    updated = runner.invoke(
        app,
        [
            "project",
            "update",
            "--agent",
            "codex",
            "--repo",
            str(repo),
            "--set",
            "model=gpt-5",
        ],
    )
    assert updated.exit_code == 0, updated.output
    assert (repo / ".codex" / "config.toml").exists()

    status = runner.invoke(app, ["--json", "project", "status", "--repo", str(repo)])
    assert status.exit_code == 0
    assert json.loads(status.stdout)[1]["agent"] == "codex"


def test_diff_check_uses_exit_code_two(isolated_env) -> None:
    _, _, repo = isolated_env
    result = runner.invoke(
        app,
        [
            "diff",
            "--scope",
            "local",
            "--agent",
            "codex",
            "--repo",
            str(repo),
            "--check",
        ],
    )
    assert result.exit_code == 2


def test_fresh_default_pack_installs_and_hook_commands_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "pack-home"
    repo = tmp_path / "pack-repo"
    home.mkdir()
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("RNF_HOME", str(home / ".rn-forge"))

    applied = runner.invoke(app, ["global", "apply"])
    initialized = runner.invoke(app, ["project", "init", "--repo", str(repo)])
    updated = runner.invoke(app, ["project", "update", "--repo", str(repo)])

    assert applied.exit_code == 0, applied.output
    assert initialized.exit_code == 0, initialized.output
    assert updated.exit_code == 0, updated.output

    global_settings = json.loads((home / ".claude/settings.json").read_text())
    local_settings = json.loads((repo / ".claude/settings.local.json").read_text())
    commands = _find_commands(global_settings) + _find_commands(local_settings)
    assert commands
    for command in commands:
        path = Path(
            command.replace("$HOME", str(home)).replace(
                "$CLAUDE_PROJECT_DIR", str(repo)
            )
        )
        assert path.is_file(), path
        assert path.stat().st_mode & 0o111, path

    codex_path = home / ".codex/config.toml"
    codex = tomlkit.loads(codex_path.read_text())
    assert codex["model"] == "gpt-5.4"
    assert tomlkit.loads(tomlkit.dumps(codex))["model"] == "gpt-5.4"


def _find_commands(value) -> list[str]:
    if isinstance(value, dict):
        commands = [value["command"]] if isinstance(value.get("command"), str) else []
        return commands + [
            command for item in value.values() for command in _find_commands(item)
        ]
    if isinstance(value, list):
        return [command for item in value for command in _find_commands(item)]
    return []
