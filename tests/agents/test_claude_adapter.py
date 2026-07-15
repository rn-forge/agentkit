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
        adapter.primary_artifact("local").native_relative.as_posix()
        == ".claude/settings.local.json"
    )


def test_claude_artifacts_and_scope_defaults() -> None:
    adapter = ClaudeAdapter()
    assert [artifact.key for artifact in adapter.artifacts("global")] == [
        "config",
        "CLAUDE.md",
        "output-styles/concise.md",
        "hooks/lib/guard-core.sh",
        "hooks/pre-bash-guard.sh",
        "hooks/user-prompt-secret-guard.sh",
        "hooks/pre-write-protect.sh",
        "hooks/session-compact-context.sh",
        "hooks/post-edit-git-stage.sh",
    ]
    assert [artifact.key for artifact in adapter.artifacts("local")] == [
        "config",
        "hooks/post-edit-format.sh",
    ]
    assert adapter.defaults("global")["outputStyle"] == "concise"
    assert "deny" in adapter.defaults("global")["permissions"]
    assert adapter.defaults("local")["permissions"]["deny"] == []
