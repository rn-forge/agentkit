from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.core.doctor import check_agent, check_environment
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

    results = check_environment("global", repo, global_root())

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
    assert all(item.agent is None for item in results)


def test_doctor_emits_one_result_per_artifact(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    apply_adapter(adapter, "global", repo)

    results = check_agent(adapter, "global", repo, global_root())

    artifact_results = [item for item in results if item.category == "artifacts"]
    assert len(artifact_results) == len(adapter.artifacts("global"))
    assert all(item.status == "ok" for item in artifact_results)


def test_doctor_reports_missing_artifact_once_without_drift(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    applied = apply_adapter(adapter, "global", repo)[0]
    applied.native_path.unlink()

    results = check_agent(adapter, "global", repo, global_root())
    config_results = [
        item
        for item in results
        if item.category == "artifacts" and item.message.startswith("config: ")
    ]

    assert len(config_results) == 1
    assert config_results[0].status == "warning"
    assert config_results[0].check == "orphan"
    assert not any(item.status == "drift" for item in results)


def test_doctor_categorizes_config_and_environment_checks(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()

    results = check_agent(adapter, "global", repo, global_root())

    categories = {(item.category, item.check) for item in results}
    assert ("config", "schema") in categories
    assert ("config", "template") in categories
    assert ("environment", "binary") in categories
    assert not any(item.check == "dependency" for item in results)
