import json
import shutil
from pathlib import Path

from rn_forge.agentkit.agents.claude import ClaudeAdapter
from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.core.artifacts import Artifact
from rn_forge.agentkit.core.io import read_config, write_config
from rn_forge.agentkit.core.manager import (
    apply_adapter,
    artifact_drifted,
    capture_adapter,
    capture_assets,
    capture_defaults,
    init_adapter,
    managed_config_path,
    remove_owned_artifacts,
    reset_adapter,
    resolve_config,
    strip_native_hooks,
    sync_adapter,
)
from rn_forge.agentkit.core.paths import global_root, project_scope_root
from rn_forge.agentkit.core.state import content_hash


def test_apply_is_idempotent_and_tracks_state(isolated_env) -> None:
    _, rnf, repo = isolated_env
    adapter = CodexAdapter()
    source = global_root() / "codex" / "config.toml"
    write_config(source, {"model": "gpt-5"})

    first = _result_for(apply_adapter(adapter, "global", repo), "config")
    second = _result_for(apply_adapter(adapter, "global", repo), "config")

    assert first.changed is True
    assert second.changed is False
    assert adapter.global_native_path().read_text() == first.rendered_path.read_text()
    state = json.loads((rnf / "share" / "agentkit" / "state.json").read_text())
    assert (
        state[str(adapter.global_native_path().resolve())]["source_layer"] == "global"
    )


def test_apply_forwards_overrides_to_the_rendered_config(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    write_config(global_root() / "codex" / "config.toml", {"model": "gpt-5"})

    applied = _result_for(
        apply_adapter(adapter, "global", repo, overrides={"model": "overridden-model"}),
        "config",
    )

    assert 'model = "overridden-model"' in applied.rendered_path.read_text()


def test_dry_run_writes_nothing_and_manual_native_is_backed_up(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    write_config(global_root() / "codex" / "config.toml", {"model": "new"})
    native = adapter.global_native_path()
    native.parent.mkdir(parents=True)
    native.write_text('model = "manual"\n')

    preview = _result_for(
        apply_adapter(adapter, "global", repo, dry_run=True), "config"
    )
    assert preview.changed is True
    assert "manual" in preview.diff
    assert not preview.rendered_path.exists()
    assert native.read_text() == 'model = "manual"\n'

    applied = _result_for(apply_adapter(adapter, "global", repo), "config")
    assert applied.backup_path is not None
    assert applied.backup_path.read_text() == 'model = "manual"\n'
    assert applied.message == ""


def test_apply_warns_when_native_drifted_since_last_apply(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    source = global_root() / "codex" / "config.toml"
    write_config(source, {"model": "managed"})
    apply_adapter(adapter, "global", repo)

    native = adapter.global_native_path()
    native.write_text('model = "manual"\n')
    write_config(source, {"model": "managed-2"})
    applied = _result_for(apply_adapter(adapter, "global", repo), "config")

    assert applied.backup_path is not None
    assert applied.backup_path.read_text() == 'model = "manual"\n'
    assert applied.message == "drift detected"


def test_project_init_does_not_overwrite_existing_config(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    first = init_adapter(adapter, repo)
    path = managed_config_path(adapter, project_scope_root(repo))
    path.write_text('model = "custom"\n')
    second = init_adapter(adapter, repo)
    assert first.changed is True
    assert second.changed is False
    assert '"custom"' in path.read_text()


def test_sync_backs_up_drift_and_reset_restores_defaults(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    source = global_root() / "codex" / "config.toml"
    write_config(source, {"model": "managed"})
    apply_adapter(adapter, "global", repo)

    native = adapter.global_native_path()
    native.write_text('model = "manual"\n')
    synced = _result_for(sync_adapter(adapter, "global", repo), "config")
    assert synced.backup_path is not None
    assert '"managed"' in native.read_text()

    reset = _result_for(reset_adapter(adapter, repo), "config")
    assert reset.backup_path is not None
    assert "model =" not in native.read_text()
    assert 'personality = "pragmatic"' in native.read_text()
    # Reset restores the empty override scaffold rather than materializing the
    # defaults into it; the defaults reach the native file through apply.
    managed = managed_config_path(adapter, global_root()).read_text()
    assert "model =" not in managed
    assert 'personality = "pragmatic"' not in managed
    assert "agentkit managed source" in managed


def test_capture_updates_managed_source_and_preserves_comments(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    source = global_root() / "codex" / "config.toml"
    source.parent.mkdir(parents=True)
    source.write_text('# keep\npersonality = "pragmatic"\n')
    applied = _result_for(apply_adapter(adapter, "global", repo), "config")
    applied.native_path.write_text(
        applied.native_path.read_text().replace(
            'personality = "pragmatic"',
            'personality = "friendly"\nmodel = "gpt-5"',
        )
    )

    result = capture_adapter(adapter, "global", repo)

    assert result.changed is True
    assert "# keep" in source.read_text()
    assert read_config(source)["personality"] == "friendly"
    assert read_config(source)["model"] == "gpt-5"


def test_capture_records_only_new_append_list_values(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = ClaudeAdapter()
    source = global_root() / "claude" / "config.toml"
    write_config(source, {"permissions": {"allow": ["Bash(existing:*)"]}})
    applied = _result_for(apply_adapter(adapter, "global", repo), "config")
    native = json.loads(applied.native_path.read_text())
    native["permissions"]["allow"].append("Bash(captured:*)")
    applied.native_path.write_text(json.dumps(native))

    capture_adapter(adapter, "global", repo)

    assert read_config(source)["permissions"]["allow"] == [
        "Bash(existing:*)",
        "Bash(captured:*)",
    ]
    merged, _ = resolve_config(adapter, "global", repo)
    assert merged.config["permissions"]["allow"] == native["permissions"]["allow"]


def test_capture_assets_writes_hand_edited_native_back_to_packaged_source(
    isolated_env, tmp_path
) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    source = tmp_path / "packaged-hook.sh"
    source.write_text("#!/usr/bin/env bash\necho packaged\n")
    artifact = Artifact(
        key="hooks/test-hook.sh",
        native_relative=Path("codex/hooks/test-hook.sh"),
        root="share",
        source=source,
        executable=True,
    )
    adapter.artifacts = lambda scope: [artifact]  # type: ignore[method-assign]

    native = adapter.native_path("global", repo, artifact)
    native.parent.mkdir(parents=True)
    native.write_text("#!/usr/bin/env bash\necho hand-edited\n")

    results = capture_assets(adapter, "global", repo)

    assert len(results) == 1
    assert results[0].changed is True
    assert source.read_text() == "#!/usr/bin/env bash\necho hand-edited\n"
    assert capture_assets(adapter, "global", repo) == []


def test_capture_assets_reports_unwritable_source_without_raising(
    isolated_env, tmp_path
) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    missing_dir = tmp_path / "no-such-dir"
    source = missing_dir / "packaged-hook.sh"
    artifact = Artifact(
        key="hooks/test-hook.sh",
        native_relative=Path("codex/hooks/test-hook.sh"),
        root="share",
        source=source,
        executable=True,
    )
    adapter.artifacts = lambda scope: [artifact]  # type: ignore[method-assign]

    native = adapter.native_path("global", repo, artifact)
    native.parent.mkdir(parents=True)
    native.write_text("#!/usr/bin/env bash\necho hand-edited\n")
    missing_dir.mkdir()
    missing_dir.chmod(0o500)
    try:
        results = capture_assets(adapter, "global", repo)
    finally:
        missing_dir.chmod(0o700)

    assert len(results) == 1
    assert results[0].changed is False
    assert "unwritable" in results[0].message


def test_capture_defaults_promotes_managed_override_into_packaged_defaults(
    isolated_env, tmp_path
) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    target = tmp_path / "global.toml"
    target.write_text('personality = "pragmatic"\n')
    adapter.defaults_path = lambda scope: target  # type: ignore[method-assign]
    write_config(global_root() / "codex" / "config.toml", {"model": "gpt-5"})

    result = capture_defaults(adapter, "global", repo)

    assert result.changed is True
    assert result.message == "captured"
    assert read_config(target)["model"] == "gpt-5"
    assert read_config(target)["personality"] == "pragmatic"

    unchanged = capture_defaults(adapter, "global", repo)
    assert unchanged.changed is False
    assert unchanged.message == "unchanged"


def test_capture_defaults_reports_no_managed_overrides_without_writing(
    isolated_env, tmp_path
) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    target = tmp_path / "global.toml"
    target.write_text('personality = "pragmatic"\n')
    adapter.defaults_path = lambda scope: target  # type: ignore[method-assign]

    result = capture_defaults(adapter, "global", repo)

    assert result.changed is False
    assert result.message == "no managed overrides"
    assert target.read_text() == 'personality = "pragmatic"\n'


def test_capture_defaults_reports_unwritable_target_without_raising(
    isolated_env, tmp_path
) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    missing_dir = tmp_path / "no-such-dir"
    target = missing_dir / "global.toml"
    adapter.defaults_path = lambda scope: target  # type: ignore[method-assign]
    write_config(global_root() / "codex" / "config.toml", {"model": "gpt-5"})
    missing_dir.mkdir()
    missing_dir.chmod(0o500)
    try:
        result = capture_defaults(adapter, "global", repo)
    finally:
        missing_dir.chmod(0o700)

    assert result.changed is False
    assert "unwritable" in result.message


def test_seed_only_artifact_is_written_once_then_left_alone(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()

    first = _result_for(apply_adapter(adapter, "local", repo), "AGENTS.md")
    assert first.changed is True
    seeded = repo / "AGENTS.md"
    assert "Read `CLAUDE.md` now" in seeded.read_text()

    seeded.write_text("# AGENTS.md\n\nHand-written guidance.\n")
    second = _result_for(apply_adapter(adapter, "local", repo), "AGENTS.md")
    assert second.changed is False
    assert second.backup_path is None
    assert seeded.read_text() == "# AGENTS.md\n\nHand-written guidance.\n"

    synced = _result_for(sync_adapter(adapter, "local", repo), "AGENTS.md")
    assert synced.changed is False
    assert seeded.read_text() == "# AGENTS.md\n\nHand-written guidance.\n"


def test_seed_only_claude_md_is_scaffolded_for_the_repo(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = ClaudeAdapter()
    result = _result_for(apply_adapter(adapter, "local", repo), "CLAUDE.md")
    assert result.changed is True
    assert "single source of agent-facing guidance" in (repo / "CLAUDE.md").read_text()


def _result_for(results, key: str):
    return next(result for result in results if result.artifact == key)


def test_capture_works_without_the_rendered_staging_copy(isolated_env) -> None:
    """Rendered/ is gitignored, so capture must not depend on it existing."""
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    source = global_root() / "codex" / "config.toml"
    write_config(source, {"personality": "pragmatic"})
    applied = _result_for(apply_adapter(adapter, "global", repo), "config")
    applied.native_path.write_text(
        'model = "gpt-5"\n' + applied.native_path.read_text()
    )
    shutil.rmtree(applied.rendered_path.parent)

    result = capture_adapter(adapter, "global", repo)

    assert result.changed is True
    assert read_config(source)["model"] == "gpt-5"


def test_capture_ignores_a_stale_rendered_staging_copy(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    source = global_root() / "codex" / "config.toml"
    write_config(source, {"model": "gpt-5"})
    applied = _result_for(apply_adapter(adapter, "global", repo), "config")
    applied.rendered_path.write_text('model = "stale"\n')

    result = capture_adapter(adapter, "global", repo)

    assert result.changed is False
    assert result.message == "unchanged"
    assert read_config(source)["model"] == "gpt-5"


def test_capture_reports_a_missing_native_config_without_failing(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()

    result = capture_adapter(adapter, "global", repo)

    assert result.changed is False
    assert result.message == "no native config"


def test_artifact_drifted_treats_a_missing_staged_copy_as_healthy(isolated_env) -> None:
    """A correct native file with no staged copy yet must not read as drift.

    This is the fresh-clone case: apply has run elsewhere and produced a
    correct native file, but nothing has been staged locally yet. `doctor`
    already treats this as healthy (see `check_agent`); `artifact_drifted`
    backs `project status` and `global list`, and must agree so the three
    surfaces do not contradict each other over the same repo state.
    """
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    source = global_root() / "codex" / "config.toml"
    write_config(source, {"model": "gpt-5"})
    applied = _result_for(apply_adapter(adapter, "global", repo), "config")
    artifact = next(a for a in adapter.artifacts("global") if a.key == applied.artifact)
    expected = content_hash(applied.rendered_path.read_text())
    applied.rendered_path.unlink()

    assert (
        artifact_drifted(artifact, applied.native_path, applied.rendered_path, expected)
        is False
    )


def test_reset_does_not_duplicate_append_merged_defaults(isolated_env) -> None:
    """Reset must converge, not append packaged defaults to themselves.

    Claude's permission lists merge by appending, so writing materialized defaults into
    the managed override and then applying would double every entry — and double again
    on each subsequent reset.
    """
    _, _, repo = isolated_env
    adapter = ClaudeAdapter()
    apply_adapter(adapter, "global", repo)
    native = adapter.global_native_path()
    baseline = json.loads(native.read_text())["permissions"]["deny"]
    assert baseline

    for _ in range(2):
        reset_adapter(adapter, repo)
        deny = json.loads(native.read_text())["permissions"]["deny"]
        assert deny == baseline
        assert len(deny) == len(set(deny))


def test_reset_backs_up_the_hand_edited_managed_source(isolated_env) -> None:
    _, rnf, repo = isolated_env
    adapter = ClaudeAdapter()
    source = managed_config_path(adapter, global_root())
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('# my note\nmodel = "custom"\n')
    apply_adapter(adapter, "global", repo)

    reset_adapter(adapter, repo)

    assert "model =" not in source.read_text()
    backups = list((rnf / "share" / "agentkit" / "backups").rglob("config.toml"))
    assert backups, "reset must snapshot the managed source before replacing it"
    recovered = backups[0].read_text()
    assert "# my note" in recovered
    assert 'model = "custom"' in recovered


def test_strip_native_hooks_removes_hooks_key_but_keeps_the_rest(isolated_env) -> None:
    _, rnf, repo = isolated_env
    adapter = ClaudeAdapter()
    apply_adapter(adapter, "global", repo)
    native = adapter.global_native_path()
    assert "hooks" in json.loads(native.read_text())

    result = strip_native_hooks(adapter, "global", repo)

    assert result.changed is True
    assert result.message == "hook registrations removed"
    parsed = json.loads(native.read_text())
    assert "hooks" not in parsed
    assert parsed["permissions"]["deny"]
    assert result.backup_path is not None
    assert "hooks" in json.loads(result.backup_path.read_text())


def test_strip_native_hooks_reports_no_native_config(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = ClaudeAdapter()

    result = strip_native_hooks(adapter, "global", repo)

    assert result.changed is False
    assert result.message == "no native config"


def test_strip_native_hooks_is_a_noop_for_codex_config(isolated_env) -> None:
    """Codex's hooks live entirely in `hooks.json`, not `config.toml`."""
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    apply_adapter(adapter, "global", repo)

    result = strip_native_hooks(adapter, "global", repo)

    assert result.changed is False
    assert result.message == "no hook registrations"


def test_strip_native_hooks_dry_run_writes_nothing(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = ClaudeAdapter()
    apply_adapter(adapter, "global", repo)
    native = adapter.global_native_path()
    before = native.read_text()

    result = strip_native_hooks(adapter, "global", repo, dry_run=True)

    assert result.changed is True
    assert result.message == "dry-run"
    assert native.read_text() == before


def test_remove_owned_artifacts_deletes_codex_hooks_manifest(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    apply_adapter(adapter, "global", repo)
    native = adapter.native_path(
        "global",
        repo,
        next(a for a in adapter.artifacts("global") if a.key == "hooks.json"),
    )
    assert native.is_file()

    results = remove_owned_artifacts(adapter, "global", repo)

    assert any(r.artifact == "hooks.json" and r.changed for r in results)
    assert not native.is_file()


def test_remove_owned_artifacts_deletes_claude_skills(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = ClaudeAdapter()
    apply_adapter(adapter, "global", repo)
    skill_artifact = next(
        a for a in adapter.artifacts("global") if a.key.startswith("skills/")
    )
    native = adapter.native_path("global", repo, skill_artifact)
    assert native.is_file()

    results = remove_owned_artifacts(adapter, "global", repo)

    assert not native.is_file()
    assert all(r.artifact != "config" for r in results)


def test_remove_owned_artifacts_leaves_a_hand_edited_file_in_place(
    isolated_env,
) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    apply_adapter(adapter, "global", repo)
    native = adapter.native_path(
        "global",
        repo,
        next(a for a in adapter.artifacts("global") if a.key == "hooks.json"),
    )
    native.write_text(native.read_text() + "\n")

    results = remove_owned_artifacts(adapter, "global", repo)

    result = next(r for r in results if r.artifact == "hooks.json")
    assert result.changed is False
    assert "modified since last apply" in result.message
    assert native.is_file()


def test_remove_owned_artifacts_dry_run_deletes_nothing(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    apply_adapter(adapter, "global", repo)
    native = adapter.native_path(
        "global",
        repo,
        next(a for a in adapter.artifacts("global") if a.key == "hooks.json"),
    )

    results = remove_owned_artifacts(adapter, "global", repo, dry_run=True)

    assert any(r.artifact == "hooks.json" and r.message == "dry-run" for r in results)
    assert native.is_file()
