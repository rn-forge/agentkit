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
    assert adapter.rendered_relative_path("global").as_posix() == ".codex/config.toml"
