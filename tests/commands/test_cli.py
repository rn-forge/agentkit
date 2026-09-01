import json
import shutil
from pathlib import Path

import tomlkit
from typer.testing import CliRunner

from rn_forge.agentkit.agents.codex.adapter import CodexAdapter
from rn_forge.agentkit.cli import app

runner = CliRunner()


def test_version_json() -> None:
    result = runner.invoke(app, ["--json", "version"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert set(data["adapters"]) == {"claude", "codex"}


def test_unknown_agent_under_json_emits_a_json_error_object(isolated_env) -> None:
    _, _, repo = isolated_env
    result = runner.invoke(
        app,
        [
            "--json",
            "project",
            "status",
            "--agent",
            "no-such-agent",
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert "no-such-agent" in payload["error"]["message"]


def test_conflicting_output_flags_under_json_emit_a_json_error_object() -> None:
    result = runner.invoke(app, ["--json", "--quiet", "version"])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert "mutually exclusive" in payload["error"]["message"]


def test_conflicting_output_flags_after_command_under_json_emit_a_json_error_object(
    isolated_env,
) -> None:
    _, _, repo = isolated_env
    result = runner.invoke(
        app, ["project", "status", "--repo", str(repo), "--json", "--quiet"]
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert "mutually exclusive" in payload["error"]["message"]


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


def test_project_remove_strips_hooks_and_working_data(isolated_env) -> None:
    _, _, repo = isolated_env
    initialized = runner.invoke(app, ["project", "init", "--repo", str(repo)])
    assert initialized.exit_code == 0, initialized.output
    assert (repo / ".codex" / "hooks.json").exists()
    assert "hooks" in json.loads((repo / ".claude/settings.local.json").read_text())
    gitignore = (repo / ".gitignore").read_text()
    assert "# BEGIN rn-forge agentkit" in gitignore

    result = runner.invoke(app, ["project", "remove", "--repo", str(repo), "--yes"])
    assert result.exit_code == 0, result.output

    local_settings = json.loads((repo / ".claude/settings.local.json").read_text())
    assert "hooks" not in local_settings
    assert local_settings["permissions"]["allow"]
    assert not (repo / ".codex" / "hooks.json").exists()
    assert not (repo / ".rn-forge" / "agentkit").exists()
    assert "# BEGIN rn-forge agentkit" not in (repo / ".gitignore").read_text()
    assert (repo / "CLAUDE.md").exists()
    assert (repo / "AGENTS.md").exists()


def test_project_remove_dry_run_changes_nothing(isolated_env) -> None:
    _, _, repo = isolated_env
    initialized = runner.invoke(app, ["project", "init", "--repo", str(repo)])
    assert initialized.exit_code == 0, initialized.output

    result = runner.invoke(app, ["project", "remove", "--repo", str(repo), "--dry-run"])
    assert result.exit_code == 0, result.output

    assert "hooks" in json.loads((repo / ".claude/settings.local.json").read_text())
    assert (repo / ".codex" / "hooks.json").exists()
    assert (repo / ".rn-forge" / "agentkit").exists()


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
    assert content.count(".rn-forge/agentkit/backups/") == 1


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
    assert ".rn-forge/agentkit/*/hooks/" in content
    assert ".rn-forge/agentkit/_common/" in content
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


def test_doctor_hides_passing_checks_until_all_is_passed(
    isolated_env, monkeypatch
) -> None:
    """Whether a check is hidden must not depend on the host's installed tools.

    Every optional binary is reported as missing so the report always contains at least
    one warning and the summary line is deterministic.
    """
    _, _, repo = isolated_env
    _fake_binaries(monkeypatch, present=())
    runner.invoke(app, ["global", "apply", "--agent", "codex"])

    default = runner.invoke(app, ["doctor", "--scope", "global", "--agent", "codex"])
    verbose = runner.invoke(
        app, ["doctor", "--scope", "global", "--agent", "codex", "--all"]
    )

    # A passing schema check has no message to match on any more — its row is
    # the finding, so assert on the row's type instead.
    assert "schema" not in default.stdout
    assert "--all to show" in default.stdout
    assert "schema" in verbose.stdout


def test_doctor_summarizes_a_fully_passing_report(isolated_env, monkeypatch) -> None:
    """With every optional binary present there is nothing to hide."""
    _, _, repo = isolated_env
    _fake_binaries(monkeypatch, present=("jq", "gitleaks", "codex", "claude"))
    runner.invoke(app, ["global", "apply", "--agent", "codex"])

    result = runner.invoke(app, ["doctor", "--scope", "global", "--agent", "codex"])

    assert "checks passed" in result.stdout
    assert "--all to show" not in result.stdout


def _fake_binaries(monkeypatch, present: tuple[str, ...]) -> None:
    """Pin optional-binary discovery so doctor output does not depend on PATH."""
    real_which = shutil.which

    def fake_which(cmd: str, *args, **kwargs) -> str | None:
        if cmd in ("jq", "gitleaks", "codex", "claude"):
            return f"/usr/bin/{cmd}" if cmd in present else None
        return real_which(cmd, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", fake_which)


def test_doctor_json_reports_every_check_with_a_category(isolated_env) -> None:
    _, _, repo = isolated_env
    result = runner.invoke(
        app, ["--json", "doctor", "--scope", "local", "--repo", str(repo)]
    )
    payload = json.loads(result.stdout)

    assert any(item["status"] == "ok" for item in payload)
    assert {item["category"] for item in payload} <= {
        "config",
        "artifacts",
        "environment",
        "state",
    }
    dependencies = [item for item in payload if item["kind"] == "dependency"]
    assert len(dependencies) == 2
    assert all(item["agent"] is None for item in dependencies)


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


def test_diff_write_captures_after_the_rendered_copy_is_removed(isolated_env) -> None:
    """A fresh clone has no gitignored rendered/ tree; --write must still work."""
    _, _, repo = isolated_env
    initialized = runner.invoke(
        app, ["project", "init", "--agent", "codex", "--repo", str(repo)]
    )
    assert initialized.exit_code == 0, initialized.output
    native = repo / ".codex" / "config.toml"
    document = tomlkit.loads(native.read_text())
    document["model"] = "gpt-5"
    native.write_text(tomlkit.dumps(document))
    shutil.rmtree(repo / ".rn-forge" / "agentkit" / "codex" / "rendered")

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
    managed = repo / ".rn-forge" / "agentkit" / "codex" / "config.toml"
    assert tomlkit.loads(managed.read_text())["model"] == "gpt-5"


def test_diff_promote_defaults_folds_managed_override_into_packaged_defaults(
    isolated_env, tmp_path, monkeypatch
) -> None:
    """--promote-defaults is opt-in and separate from --write's native capture."""
    _, _, repo = isolated_env
    target = tmp_path / "local.toml"
    target.write_text("")
    monkeypatch.setattr(CodexAdapter, "defaults_path", lambda self, scope: target)
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
            "--promote-defaults",
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
    assert record["capture_defaults"]["changed"] is True
    assert tomlkit.loads(target.read_text())["model"] == "gpt-5"


def test_diff_write_reports_nothing_to_capture_without_a_native_config(
    isolated_env,
) -> None:
    _, _, repo = isolated_env
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
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Nothing to capture: no native config." in result.output


def test_diff_hides_the_defaults_layer_until_all_is_passed(isolated_env) -> None:
    _, _, repo = isolated_env
    initialized = runner.invoke(
        app, ["project", "init", "--agent", "claude", "--repo", str(repo)]
    )
    assert initialized.exit_code == 0, initialized.output

    default_output = runner.invoke(
        app, ["diff", "--scope", "local", "--agent", "claude", "--repo", str(repo)]
    )
    verbose = runner.invoke(
        app,
        ["diff", "--all", "--scope", "local", "--agent", "claude", "--repo", str(repo)],
    )

    assert default_output.exit_code == 0, default_output.output
    assert "No layers override the packaged defaults." in default_output.output
    assert "keys from packaged defaults (--all to show)" in default_output.output
    assert "permissions.allow" not in default_output.output
    assert verbose.exit_code == 0, verbose.output
    assert "permissions.allow" in verbose.output
    assert "(--all to show)" not in verbose.output


def test_diff_summarizes_drift_per_artifact(isolated_env) -> None:
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
        app, ["diff", "--scope", "local", "--agent", "codex", "--repo", str(repo)]
    )

    assert result.exit_code == 0, result.output
    assert "checked artifacts" in result.output
    assert '-model = "gpt-5"' in result.output


def test_diff_write_captures_hand_edited_hook_into_packaged_source(
    isolated_env, tmp_path, monkeypatch
) -> None:
    _, _, repo = isolated_env
    fake_scripts_dir = tmp_path / "packaged-scripts"
    shutil.copytree(CodexAdapter()._shared_scripts_dir, fake_scripts_dir)
    monkeypatch.setattr(
        CodexAdapter, "_shared_scripts_dir", property(lambda self: fake_scripts_dir)
    )

    initialized = runner.invoke(
        app, ["project", "init", "--agent", "codex", "--repo", str(repo)]
    )
    assert initialized.exit_code == 0, initialized.output
    hook = repo / ".rn-forge" / "agentkit" / "codex" / "hooks" / "post-edit-format.sh"
    hook.write_text("#!/usr/bin/env bash\necho hand-edited\n")

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
    captured = {item["artifact"]: item for item in record["capture_assets"]}
    assert captured["hooks/post-edit-format.sh"]["changed"] is True
    assert (
        fake_scripts_dir / "post-edit-format.sh"
    ).read_text() == "#!/usr/bin/env bash\necho hand-edited\n"


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


def test_doctor_reports_artifact_rows_as_source_and_target(isolated_env) -> None:
    """An artifact row carries two real paths and no prose."""
    _, _, repo = isolated_env
    runner.invoke(app, ["project", "init", "--repo", str(repo)])

    result = runner.invoke(
        app, ["--json", "doctor", "--scope", "local", "--repo", str(repo), "--all"]
    )
    payload = json.loads(result.stdout)
    artifacts = [item for item in payload if item["category"] == "artifacts"]

    assert artifacts
    for item in artifacts:
        assert item["source"] and Path(item["source"]).exists()
        assert item["target"]
        assert item["message"] == ""
        assert item["kind"] in {"config", "hook", "skill", "doc"}


def test_doctor_abbreviates_paths_without_truncating_them(isolated_env) -> None:
    """Roots are factored into a legend; no path is ever elided to an ellipsis."""
    _, _, repo = isolated_env
    runner.invoke(app, ["project", "init", "--repo", str(repo)])

    result = runner.invoke(
        app, ["doctor", "--scope", "local", "--repo", str(repo), "--all"]
    )

    assert "$PKG   =" in result.stdout
    assert "$REPO  =" in result.stdout
    assert "\u2026" not in result.stdout


def test_doctor_exit_code_follows_severity_not_status(
    isolated_env, monkeypatch
) -> None:
    """`missing` is a status; only an `error` severity fails the command."""
    _, _, repo = isolated_env
    _fake_binaries(monkeypatch, present=("gitleaks", "codex", "claude"))

    result = runner.invoke(app, ["doctor", "--scope", "local", "--repo", str(repo)])

    payload = runner.invoke(
        app, ["--json", "doctor", "--scope", "local", "--repo", str(repo)]
    )
    missing_jq = [
        item
        for item in json.loads(payload.stdout)
        if item["kind"] == "dependency" and "jq" in item["message"]
    ]
    assert missing_jq and missing_jq[0]["severity"] == "error"
    assert missing_jq[0]["status"] == "missing"
    assert result.exit_code == 1
