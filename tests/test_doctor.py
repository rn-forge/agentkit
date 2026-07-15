from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.core.doctor import check_agent
from rn_forge.agentkit.core.io import write_config
from rn_forge.agentkit.core.manager import apply_adapter


def test_doctor_detects_native_drift_and_orphans(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("HOME", str(home))
    adapter = CodexAdapter()
    write_config(home / ".agentkit" / "codex" / "config.toml", {"model": "managed"})
    applied = apply_adapter(adapter, "global", repo)
    applied.native_path.write_text('model = "manual"\n')
    orphan = applied.rendered_path.parent / "old.toml"
    orphan.write_text("old = true\n")

    results = check_agent(adapter, "global", repo, home / ".agentkit")

    assert any(item.status == "drift" for item in results)
    assert any(
        item.check == "orphan" and "old.toml" in item.message for item in results
    )
