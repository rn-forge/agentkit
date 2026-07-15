import json
from pathlib import Path

from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.core.io import write_config
from rn_forge.agentkit.core.manager import (
    apply_adapter,
    init_adapter,
    managed_config_path,
    reset_adapter,
    sync_adapter,
)


def _home_and_repo(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home, repo


def test_apply_is_idempotent_and_tracks_state(tmp_path, monkeypatch) -> None:
    home, repo = _home_and_repo(tmp_path, monkeypatch)
    adapter = CodexAdapter()
    source = home / ".agentkit" / "codex" / "config.toml"
    write_config(source, {"model": "gpt-5"})

    first = apply_adapter(adapter, "global", repo)
    second = apply_adapter(adapter, "global", repo)

    assert first.changed is True
    assert second.changed is False
    assert adapter.global_native_path().read_text() == first.rendered_path.read_text()
    state = json.loads((home / ".agentkit" / "state.json").read_text())
    assert (
        state[str(adapter.global_native_path().resolve())]["source_layer"] == "global"
    )


def test_dry_run_writes_nothing_and_manual_native_is_backed_up(
    tmp_path, monkeypatch
) -> None:
    home, repo = _home_and_repo(tmp_path, monkeypatch)
    adapter = CodexAdapter()
    write_config(home / ".agentkit" / "codex" / "config.toml", {"model": "new"})
    native = adapter.global_native_path()
    native.parent.mkdir(parents=True)
    native.write_text('model = "manual"\n')

    preview = apply_adapter(adapter, "global", repo, dry_run=True)
    assert preview.changed is True
    assert "manual" in preview.diff
    assert not preview.rendered_path.exists()
    assert native.read_text() == 'model = "manual"\n'

    applied = apply_adapter(adapter, "global", repo)
    assert applied.backup_path is not None
    assert applied.backup_path.read_text() == 'model = "manual"\n'


def test_project_init_does_not_overwrite_existing_config(tmp_path, monkeypatch) -> None:
    _, repo = _home_and_repo(tmp_path, monkeypatch)
    adapter = CodexAdapter()
    first = init_adapter(adapter, repo)
    path = managed_config_path(adapter, repo / ".agentkit")
    path.write_text('model = "custom"\n')
    second = init_adapter(adapter, repo)
    assert first.changed is True
    assert second.changed is False
    assert '"custom"' in path.read_text()


def test_sync_backs_up_drift_and_reset_restores_defaults(tmp_path, monkeypatch) -> None:
    home, repo = _home_and_repo(tmp_path, monkeypatch)
    adapter = CodexAdapter()
    source = home / ".agentkit" / "codex" / "config.toml"
    write_config(source, {"model": "managed"})
    apply_adapter(adapter, "global", repo)

    native = adapter.global_native_path()
    native.write_text('model = "manual"\n')
    synced = sync_adapter(adapter, "global", repo)
    assert synced.backup_path is not None
    assert '"managed"' in native.read_text()

    reset = reset_adapter(adapter, repo)
    assert reset.backup_path is not None
    assert "model" not in native.read_text()
    assert "model" not in managed_config_path(adapter, home / ".agentkit").read_text()
