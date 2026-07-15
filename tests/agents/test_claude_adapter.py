import json

from rn_forge.agentkit.agents.claude import ClaudeAdapter


def test_claude_render_and_parse(tmp_path) -> None:
    adapter = ClaudeAdapter()
    rendered = adapter.render(
        {"permissions": {"allow": ["Read"]}, "env": {"MODE": "test"}}, scope="local"
    )
    assert json.loads(rendered)["permissions"]["allow"] == ["Read"]
    path = tmp_path / "settings.json"
    path.write_text(rendered)
    assert adapter.parse_native(path)["env"] == {"MODE": "test"}
    assert (
        adapter.rendered_relative_path("local").as_posix()
        == ".claude/settings.local.json"
    )
