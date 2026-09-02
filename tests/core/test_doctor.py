from rn_forge.agentkit.agents.claude import ClaudeAdapter
from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.core.doctor import HEALTHY, check_agent, check_environment
from rn_forge.agentkit.core.io import write_config
from rn_forge.agentkit.core.operations import apply_adapter
from rn_forge.agentkit.core.paths import global_root, project_scope_root


def _result_for(results, key: str):
    return next(result for result in results if result.artifact == key)


def test_doctor_detects_native_drift_and_orphans(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    write_config(global_root() / "codex" / "config.toml", {"model": "managed"})
    applied = _result_for(apply_adapter(adapter, "global", repo), "config")
    applied.native_path.write_text('model = "manual"\n')
    orphan = applied.rendered_path.parent / "old.toml"
    orphan.write_text("old = true\n")

    results = check_agent(adapter, "global", repo, global_root())

    assert any(item.status == "drift" for item in results)
    assert any(
        item.status == "orphan" and item.target and item.target.name == "old.toml"
        for item in results
    )


def test_doctor_reports_hook_dependencies(isolated_env, monkeypatch) -> None:
    _, _, repo = isolated_env
    monkeypatch.setattr(
        "rn_forge.agentkit.core.doctor.shutil.which", lambda _name: None
    )

    results = check_environment("global", repo, global_root())

    assert any(
        item.severity == "error"
        and item.status == "missing"
        and item.kind == "dependency"
        and "jq" in item.message
        for item in results
    )
    assert any(
        item.severity == "warning"
        and item.status == "missing"
        and item.kind == "dependency"
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
    assert all(item.status in HEALTHY for item in artifact_results)
    assert all(item.source and item.target for item in artifact_results)


def test_doctor_reports_missing_artifact_once_without_drift(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    applied = _result_for(apply_adapter(adapter, "global", repo), "config")
    applied.native_path.unlink()

    results = check_agent(adapter, "global", repo, global_root())
    config_results = [
        item
        for item in results
        if item.category == "artifacts" and item.target == applied.native_path
    ]

    assert len(config_results) == 1
    assert config_results[0].status == "unsynced"
    assert config_results[0].severity == "warning"
    assert not any(item.status == "drift" for item in results)


def test_doctor_categorizes_config_and_environment_checks(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()

    results = check_agent(adapter, "global", repo, global_root())

    categories = {(item.category, item.kind) for item in results}
    assert ("config", "schema") in categories
    assert ("config", "template") in categories
    assert ("environment", "binary") in categories
    assert not any(item.kind == "dependency" for item in results)


def test_doctor_detects_stale_copies_that_still_match_each_other(isolated_env) -> None:
    """Two equally out-of-date copies are not 'in sync'.

    Comparing the staged copy with the native copy alone hides a change to a template, a
    default, or a packaged asset made after the last apply.
    """
    _, rnf, repo = isolated_env
    adapter = CodexAdapter()
    source = global_root() / "codex" / "config.toml"
    write_config(source, {"model": "first"})
    apply_adapter(adapter, "global", repo)

    scope_root = rnf / "share" / "agentkit"
    healthy = check_agent(adapter, "global", repo, scope_root)
    assert not [item for item in healthy if item.status == "drift"]

    # Change the managed source without applying: both copies now predate it.
    write_config(source, {"model": "second"})

    results = check_agent(adapter, "global", repo, scope_root)
    drifted = [item for item in results if item.status == "drift"]
    assert drifted, "stale-but-identical copies must not report as in sync"


def test_doctor_flags_a_stale_staged_copy_distinctly(isolated_env) -> None:
    _, rnf, repo = isolated_env
    adapter = CodexAdapter()
    apply_adapter(adapter, "global", repo)
    scope_root = rnf / "share" / "agentkit"

    artifact = adapter.primary_artifact("global")
    rendered = adapter.rendered_path(scope_root, "global", artifact)
    rendered.write_text("# stale staging\n")

    results = check_agent(adapter, "global", repo, scope_root)
    staged = [item for item in results if item.status == "stale"]
    assert staged
    # The out-of-date file is the staged copy, so that is what `target` names.
    assert staged[0].target == rendered


def test_doctor_does_not_call_an_edited_seed_file_drift(isolated_env) -> None:
    """Apply leaves seed files alone, so doctor must not compare their content."""
    _, _, repo = isolated_env
    adapter = ClaudeAdapter()
    scope_root = project_scope_root(repo)
    apply_adapter(adapter, "local", repo)

    seeds = [item for item in adapter.artifacts("local") if item.seed_only]
    assert seeds, "this test needs at least one seed-only artifact"
    for artifact in seeds:
        native = adapter.native_path("local", repo, artifact)
        native.write_text("# my own project notes\n")

    results = check_agent(adapter, "local", repo, scope_root)
    assert not [item for item in results if item.status == "drift"]
    assert [item for item in results if item.status == "seeded"]


def test_doctor_reports_a_missing_seed_file(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = ClaudeAdapter()
    scope_root = project_scope_root(repo)
    apply_adapter(adapter, "local", repo)

    for artifact in adapter.artifacts("local"):
        if artifact.seed_only:
            adapter.native_path("local", repo, artifact).unlink()

    results = check_agent(adapter, "local", repo, scope_root)
    assert [
        item
        for item in results
        if item.status == "missing" and item.severity == "warning"
    ]
