from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.core.doctor import check_agent
from rn_forge.agentkit.core.io import write_config
from rn_forge.agentkit.core.manager import apply_adapter
from rn_forge.agentkit.core.paths import global_root


def test_doctor_detects_native_drift_and_orphans(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    write_config(global_root() / "codex" / "config.toml", {"model": "managed"})
    applied = apply_adapter(adapter, "global", repo)[0]
    applied.native_path.write_text('model = "manual"\n')
    orphan = applied.rendered_path.parent / "old.toml"
    orphan.write_text("old = true\n")

    results = check_agent(adapter, "global", repo, global_root())

    assert any(item.status == "drift" for item in results)
    assert any(
        item.check == "orphan" and "old.toml" in item.message for item in results
    )


def test_doctor_reports_hook_dependencies(isolated_env, monkeypatch) -> None:
    _, _, repo = isolated_env
    monkeypatch.setattr(
        "rn_forge.agentkit.core.doctor.shutil.which", lambda _name: None
    )

    results = check_agent(CodexAdapter(), "global", repo, global_root())

    assert any(
        item.status == "error" and item.check == "dependency" and "jq" in item.message
        for item in results
    )
    assert any(
        item.status == "warning"
        and item.check == "dependency"
        and "gitleaks" in item.message
        for item in results
    )
