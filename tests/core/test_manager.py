import json
import shutil
from pathlib import Path

from rn_forge.agentkit.agents.claude import ClaudeAdapter
from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.core.artifacts import Artifact
from rn_forge.agentkit.core.io import read_config, write_config
from rn_forge.agentkit.core.manager import (
    apply_adapter,
    capture_adapter,
    capture_assets,
    init_adapter,
    managed_config_path,
    reset_adapter,
    resolve_config,
    sync_adapter,
)
from rn_forge.agentkit.core.paths import global_root, project_scope_root


def test_apply_is_idempotent_and_tracks_state(isolated_env) -> None:
    _, rnf, repo = isolated_env
    adapter = CodexAdapter()
    source = global_root() / "codex" / "config.toml"
    write_config(source, {"model": "gpt-5"})

    first = apply_adapter(adapter, "global", repo)[0]
    second = apply_adapter(adapter, "global", repo)[0]

    assert first.changed is True
    assert second.changed is False
    assert adapter.global_native_path().read_text() == first.rendered_path.read_text()
    state = json.loads((rnf / "share" / "agentkit" / "state.json").read_text())
    assert (
        state[str(adapter.global_native_path().resolve())]["source_layer"] == "global"
    )


def test_dry_run_writes_nothing_and_manual_native_is_backed_up(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    write_config(global_root() / "codex" / "config.toml", {"model": "new"})
    native = adapter.global_native_path()
    native.parent.mkdir(parents=True)
    native.write_text('model = "manual"\n')

    preview = apply_adapter(adapter, "global", repo, dry_run=True)[0]
    assert preview.changed is True
    assert "manual" in preview.diff
    assert not preview.rendered_path.exists()
    assert native.read_text() == 'model = "manual"\n'

    applied = apply_adapter(adapter, "global", repo)[0]
    assert applied.backup_path is not None
    assert applied.backup_path.read_text() == 'model = "manual"\n'


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
    synced = sync_adapter(adapter, "global", repo)[0]
    assert synced.backup_path is not None
    assert '"managed"' in native.read_text()

    reset = reset_adapter(adapter, repo)[0]
    assert reset.backup_path is not None
    assert "model =" not in native.read_text()
    assert 'personality = "pragmatic"' in native.read_text()
    managed = managed_config_path(adapter, global_root()).read_text()
    assert "model =" not in managed
    assert 'personality = "pragmatic"' in managed


def test_capture_updates_managed_source_and_preserves_comments(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    source = global_root() / "codex" / "config.toml"
    source.parent.mkdir(parents=True)
    source.write_text('# keep\npersonality = "pragmatic"\n')
    applied = apply_adapter(adapter, "global", repo)[0]
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
    applied = apply_adapter(adapter, "global", repo)[0]
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
    """rendered/ is gitignored, so capture must not depend on it existing."""
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    source = global_root() / "codex" / "config.toml"
    write_config(source, {"personality": "pragmatic"})
    applied = apply_adapter(adapter, "global", repo)[0]
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
    applied = apply_adapter(adapter, "global", repo)[0]
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
