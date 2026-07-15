import json

from typer.testing import CliRunner

from rn_forge.agentkit.cli import app

runner = CliRunner()


def test_version_json() -> None:
    result = runner.invoke(app, ["--json", "version"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert set(data["adapters"]) == {"claude", "codex"}


def test_project_init_update_status(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("HOME", str(home))

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


def test_diff_check_uses_exit_code_two(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("HOME", str(home))
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
