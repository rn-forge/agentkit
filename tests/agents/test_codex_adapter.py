import json
from pathlib import Path

import tomlkit

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
        "hooks/pre-write-protect.sh",
    ]
    assert [artifact.key for artifact in adapter.artifacts("local")] == [
        "config",
        "hooks.json",
        "hooks/post-edit-format.sh",
    ]
    assert "model" not in adapter.defaults("global")
    assert adapter.defaults("global")["personality"] == "pragmatic"
    assert adapter.defaults("global")["features"]["hooks"] is True
    assert "model" not in adapter.defaults("local")


def test_codex_instruction_snapshot_matches_shared_template() -> None:
    adapter = CodexAdapter()
    artifact = next(
        item for item in adapter.artifacts("global") if item.key == "AGENTS.md"
    )
    rendered = adapter.render_artifact(artifact, {}, "global")
    snapshot = Path("src/rn_forge/agentkit/agents/codex/assets/AGENTS.md")

    assert isinstance(rendered, str)
    assert rendered.encode() == snapshot.read_bytes()


def test_codex_hook_registrations_cover_write_and_format_events() -> None:
    assets = Path("src/rn_forge/agentkit/agents/codex/assets")
    global_hooks = json.loads((assets / "hooks.json").read_text())["hooks"]
    local_hooks = json.loads((assets / "hooks.local.json").read_text())["hooks"]

    assert {group["matcher"] for group in global_hooks["PreToolUse"]} == {
        "Bash",
        "Edit|Write",
    }
    assert local_hooks["PostToolUse"][0]["matcher"] == "Edit|Write"
    assert all(
        hook["statusMessage"]
        for groups in global_hooks.values()
        for group in groups
        for hook in group["hooks"]
    )


def test_codex_defaults_render_and_validate_for_both_scopes() -> None:
    adapter = CodexAdapter()
    for scope in ("global", "local"):
        defaults = adapter.defaults(scope)
        assert adapter.validate(defaults) == []
        rendered = tomlkit.loads(adapter.render(defaults, scope=scope))
        assert isinstance(rendered.unwrap(), dict)
