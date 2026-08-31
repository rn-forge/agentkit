import json
from pathlib import Path

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
    global_keys = [artifact.key for artifact in adapter.artifacts("global")]
    assert global_keys[:10] == [
        "config",
        "CLAUDE.md",
        "output-styles/concise.md",
        "hooks/guard-core.sh",
        "hooks/pre-bash-guard.sh",
        "hooks/user-prompt-secret-guard.sh",
        "hooks/pre-write-protect.sh",
        "hooks/session-compact-context.sh",
        "hooks/post-write-unwrap-md.sh",
        "hooks/unwrap_md.py",
    ]
    skill_keys = global_keys[10:]
    assert skill_keys and all(key.startswith("skills/") for key in skill_keys)
    assert "skills/go-task-setup/SKILL.md" in skill_keys
    assert "skills/mkdocs-site-setup/SKILL.md" in skill_keys
    assert "skills/sonar-cleanup/SKILL.md" in skill_keys
    assert [artifact.key for artifact in adapter.artifacts("local")] == [
        "config",
        "CLAUDE.md",
        "hooks/post-edit-format.sh",
    ]
    seed = next(
        artifact
        for artifact in adapter.artifacts("local")
        if artifact.key == "CLAUDE.md"
    )
    assert seed.seed_only
    assert seed.native_relative == Path("CLAUDE.md")
    assert adapter.defaults("global")["outputStyle"] == "concise"
    assert "deny" in adapter.defaults("global")["permissions"]
    assert adapter.defaults("local")["permissions"]["deny"] == []
    local_permissions = adapter.defaults("local")["permissions"]
    assert "Bash" not in local_permissions["allow"]
    assert "MultiEdit" not in local_permissions["allow"]
    assert "Bash(git status:*)" in local_permissions["allow"]
    assert "Bash(gh pr create:*)" in local_permissions["ask"]
    global_defaults = adapter.defaults("global")
    assert "PostCompact" not in global_defaults["hooks"]
    assert {
        "Read(**/.kube/config)",
        "Read(**/*.p12)",
        "Read(**/*.pfx)",
        "Read(**/*.gpg)",
        "Read(**/*.asc)",
        "Read(**/service-account*.json)",
        "Read(**/.ssh/**)",
        "Read(**/.aws/**)",
    } <= set(global_defaults["permissions"]["deny"])
    assert all(
        hook["statusMessage"]
        for groups in global_defaults["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    )


def test_claude_instruction_snapshots_match_shared_templates() -> None:
    adapter = ClaudeAdapter()
    assets = Path("src/rn_forge/agentkit/agents/claude/assets")
    for key, snapshot in (
        ("CLAUDE.md", assets / "CLAUDE.md"),
        ("output-styles/concise.md", assets / "output-styles/concise.md"),
    ):
        artifact = next(item for item in adapter.artifacts("global") if item.key == key)
        rendered = adapter.render_artifact(artifact, {}, "global")
        assert isinstance(rendered, str)
        assert rendered.encode() == snapshot.read_bytes()


def test_claude_defaults_render_and_validate_for_both_scopes() -> None:
    adapter = ClaudeAdapter()
    for scope in ("global", "local"):
        defaults = adapter.defaults(scope)
        assert adapter.validate(defaults) == []
        assert isinstance(json.loads(adapter.render(defaults, scope=scope)), dict)
