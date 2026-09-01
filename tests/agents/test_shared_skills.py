"""Skills are single-sourced and rendered per agent, like shared instructions."""

from __future__ import annotations

from pathlib import Path

from rn_forge.agentkit.agents.claude.adapter import ClaudeAdapter
from rn_forge.agentkit.agents.codex.adapter import CodexAdapter


def _skills(adapter):
    return {
        artifact.key: artifact
        for artifact in adapter.artifacts("global")
        if artifact.key.startswith("skills/")
    }


def test_both_agents_ship_the_same_skill_set_under_native_roots() -> None:
    claude, codex = _skills(ClaudeAdapter()), _skills(CodexAdapter())

    assert claude.keys() == codex.keys()
    assert "skills/sonar-cleanup/SKILL.md" in claude
    assert claude["skills/sonar-cleanup/SKILL.md"].native_relative == Path(
        ".claude/skills/sonar-cleanup/SKILL.md"
    )
    assert codex["skills/sonar-cleanup/SKILL.md"].native_relative == Path(
        ".codex/skills/sonar-cleanup/SKILL.md"
    )


def test_bundled_resources_copy_verbatim_and_keep_foreign_placeholders() -> None:
    """Go-task `{{.VAR}}` and Actions `${{ }}` must not be rendered as Jinja."""
    adapter = ClaudeAdapter()
    workflow = _skills(adapter)[
        "skills/mkdocs-site-setup/assets/docs-deploy.yml.template"
    ]

    assert workflow.template is None
    assert workflow.source is not None
    assert "${{" in adapter.render_artifact(workflow, {}, "global").decode()


def test_harness_specific_lines_branch_on_agent() -> None:
    claude, codex = ClaudeAdapter(), CodexAdapter()
    key = "skills/go-task-setup/SKILL.md"
    claude_task = claude.render_skill_artifact(_skills(claude)[key])
    codex_task = codex.render_skill_artifact(_skills(codex)[key])

    assert "allowed-tools:" in claude_task
    assert "allowed-tools:" not in codex_task

    key = "skills/sonar-cleanup/SKILL.md"
    assert "ToolSearch" in claude.render_skill_artifact(_skills(claude)[key])
    assert "ToolSearch" not in codex.render_skill_artifact(_skills(codex)[key])


def test_every_skill_template_renders_for_every_agent() -> None:
    for adapter in (ClaudeAdapter(), CodexAdapter()):
        assert adapter.template_errors() == []
