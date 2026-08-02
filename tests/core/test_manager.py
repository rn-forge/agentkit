import json
from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.core.io import write_config
from rn_forge.agentkit.core.manager import (
    apply_adapter,
    init_adapter,
    managed_config_path,
    reset_adapter,
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
