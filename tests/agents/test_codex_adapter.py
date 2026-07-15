from rn_forge.agentkit.agents.codex import CodexAdapter


def test_codex_render_and_parse(tmp_path) -> None:
    adapter = CodexAdapter()
    rendered = adapter.render(
        {"model": "gpt-5", "features": {"shell_tool": True}}, scope="global"
    )
    path = tmp_path / "config.toml"
    path.write_text(rendered)
    parsed = adapter.parse_native(path)
    assert parsed["model"] == "gpt-5"
    assert parsed["features"]["shell_tool"] is True
    assert (
        adapter.primary_artifact("global").native_relative.as_posix()
        == ".codex/config.toml"
    )


def test_codex_artifacts_and_scope_defaults() -> None:
    adapter = CodexAdapter()
    assert [artifact.key for artifact in adapter.artifacts("global")] == [
        "config",
        "AGENTS.md",
        "hooks.json",
        "hooks/lib/guard-core.sh",
        "hooks/pre-bash-guard.sh",
        "hooks/user-prompt-secret-guard.sh",
        "skills/repo-context/SKILL.md",
        "skills/repo-context/agents/openai.yaml",
    ]
    assert [artifact.key for artifact in adapter.artifacts("local")] == ["config"]
    assert adapter.defaults("global")["model"] == "gpt-5.4"
    assert "model" not in adapter.defaults("local")
