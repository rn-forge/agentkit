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
    assert (repo / ".codex" / "config.toml").exists()
    assert (repo / ".codex" / "hooks.json").exists()

    status = runner.invoke(
        app,
        ["--json", "project", "status", "--agent", "codex", "--repo", str(repo)],
    )
    assert status.exit_code == 0
    status_data = json.loads(status.stdout)[0]
    assert status_data["rendered"] is True
    assert status_data["drift"] is False

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


def test_project_init_scaffolds_gitignore_once(isolated_env) -> None:
    _, _, repo = isolated_env
    gitignore = repo / ".gitignore"
    gitignore.write_text("*.log\n", encoding="utf-8")

    first = runner.invoke(
        app, ["project", "init", "--agent", "codex", "--repo", str(repo)]
    )
    second = runner.invoke(
        app, ["project", "init", "--agent", "codex", "--repo", str(repo)]
    )

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    content = gitignore.read_text(encoding="utf-8")
    assert content.startswith("*.log\n")
    assert content.count("# BEGIN rn-forge agentkit") == 1
    assert content.count("/.rn-forge/agentkit/backups/") == 1


def test_project_init_refreshes_stale_gitignore_block(isolated_env) -> None:
    _, _, repo = isolated_env
    gitignore = repo / ".gitignore"
    gitignore.write_text(
        "node_modules/\n\n"
        "# BEGIN rn-forge agentkit\n"
        "/.rn-forge/agentkit/hooks/\n"
        "# END rn-forge agentkit\n\n"
        "*.log\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app, ["project", "init", "--agent", "codex", "--repo", str(repo)]
    )

    assert result.exit_code == 0, result.output
    content = gitignore.read_text(encoding="utf-8")
    assert "/.rn-forge/agentkit/hooks/\n" not in content
    assert "/.rn-forge/agentkit/*/hooks/" in content
    assert "/.rn-forge/agentkit/_common/" in content
    assert content.count("# BEGIN rn-forge agentkit") == 1
    assert content.startswith("node_modules/\n")
    assert content.endswith("*.log\n")


def test_project_init_dry_run_writes_nothing(isolated_env) -> None:
    _, _, repo = isolated_env

    result = runner.invoke(
        app,
        [
            "project",
            "init",
            "--agent",
            "codex",
            "--repo",
            str(repo),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert not (repo / ".rn-forge").exists()
    assert not (repo / ".codex").exists()
    assert not (repo / ".gitignore").exists()


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


def test_diff_write_captures_native_config(isolated_env) -> None:
    _, _, repo = isolated_env
    initialized = runner.invoke(
        app, ["project", "init", "--agent", "codex", "--repo", str(repo)]
    )
    assert initialized.exit_code == 0, initialized.output
    native = repo / ".codex" / "config.toml"
    document = tomlkit.loads(native.read_text())
    document["model"] = "gpt-5"
    native.write_text(tomlkit.dumps(document))

    result = runner.invoke(
        app,
        [
            "diff",
            "--write",
            "--scope",
            "local",
            "--agent",
            "codex",
            "--repo",
            str(repo),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    record = json.loads(result.stdout)[0]
    assert record["capture"]["changed"] is True
    assert record["artifacts"][0]["drift"] is False
    managed = repo / ".rn-forge" / "agentkit" / "codex" / "config.toml"
    assert tomlkit.loads(managed.read_text())["model"] == "gpt-5"


def test_install_commands_warn_when_jq_is_missing(isolated_env, monkeypatch) -> None:
    _, _, repo = isolated_env
    monkeypatch.setattr(
        "rn_forge.agentkit.commands.common.shutil.which", lambda _name: None
    )

    applied = runner.invoke(app, ["global", "apply", "--agent", "codex"])
    initialized = runner.invoke(
        app, ["project", "init", "--agent", "codex", "--repo", str(repo)]
    )

    assert applied.exit_code == 0, applied.output
    assert initialized.exit_code == 0, initialized.output
    assert "WARNING: jq is not installed" in applied.output
    assert "WARNING: jq is not installed" in initialized.output


def test_global_apply_uses_one_backup_directory_per_invocation(isolated_env) -> None:
    home, rnf, _ = isolated_env

    initial = runner.invoke(app, ["global", "apply", "--agent", "codex"])
    assert initial.exit_code == 0, initial.output
    (home / ".codex/config.toml").write_text('model = "manual"\n')
    (home / ".codex/AGENTS.md").write_text("manual instructions\n")

    applied = runner.invoke(app, ["global", "apply", "--agent", "codex"])
    assert applied.exit_code == 0, applied.output

    backup_root = rnf / "share" / "agentkit" / "backups"
    backup_runs = list(backup_root.iterdir())
    assert len(backup_runs) == 1
    assert (backup_runs[0] / ".codex/config.toml").read_text() == 'model = "manual"\n'
    assert (backup_runs[0] / ".codex/AGENTS.md").read_text() == (
        "manual instructions\n"
    )

    (home / ".codex/config.toml").write_text('model = "manual again"\n')
    reapplied = runner.invoke(app, ["global", "apply", "--agent", "codex"])
    assert reapplied.exit_code == 0, reapplied.output
    assert len(list(backup_root.iterdir())) == 2


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
    assert "model" not in codex
    assert codex["personality"] == "pragmatic"
    assert tomlkit.loads(tomlkit.dumps(codex))["features"]["hooks"] is True


def _find_commands(value) -> list[str]:
    if isinstance(value, dict):
        commands = [value["command"]] if isinstance(value.get("command"), str) else []
        return commands + [
            command for item in value.values() for command in _find_commands(item)
        ]
    if isinstance(value, list):
        return [command for item in value for command in _find_commands(item)]
    return []
