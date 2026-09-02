"""Implement Claude Code JSON rendering and default-pack artifacts.

The adapter combines the Claude schema, packaged scope defaults, Jinja JSON templates,
native ``.claude`` paths, and shared hook assets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ...core.artifacts import Artifact
from ...core.render import RenderEngine
from ..base import AgentAdapter, Scope
from .schema import ClaudeConfig


_CLAUDE_MD = "CLAUDE.md"


class ClaudeAdapter(AgentAdapter):
    """Manage Claude Code global and repository-local configuration files."""

    name = "claude"
    binary_name = "claude"
    _defaults_suffix = ".json"

    def schema(self) -> type[ClaudeConfig]:
        """Return the Claude settings schema."""
        return ClaudeConfig

    def _config_artifact(self, scope: Scope) -> Artifact:
        filename = "settings.json" if scope == "global" else "settings.local.json"
        return Artifact(
            key="config",
            native_relative=Path(".claude") / filename,
            template=f"{scope}.j2",
        )

    def _global_artifacts(self) -> list[Artifact]:
        """Declare Claude config, instruction, style, and hook artifacts."""
        return [
            self._guard_core_artifact(),
            *self._hook_script_artifacts(
                (
                    "pre-bash-guard.sh",
                    "user-prompt-secret-guard.sh",
                    "pre-write-protect.sh",
                    "session-compact-context.sh",
                )
            ),
            self._config_artifact("global"),
            Artifact(
                _CLAUDE_MD,
                Path(".claude/CLAUDE.md"),
                kind="doc",
                template="CLAUDE.md.j2",
                template_root=self._shared_instructions_dir,
            ),
            Artifact(
                "output-styles/concise.md",
                Path(".claude/output-styles/concise.md"),
                kind="doc",
                template="concise.md.j2",
                template_root=self._shared_instructions_dir,
            ),
            *self.skill_artifacts(self._skills_dir),
        ]

    def _local_artifacts(self) -> list[Artifact]:
        """Declare Claude local-scope config, instruction seed, and hook artifacts."""
        # Hook scripts are declared before `config`, which the packaged
        # defaults point at by path (see `defaults/*.json`'s "hooks" key), so
        # a written config never lands pointing at a script that does not
        # exist yet.
        return [
            self._post_edit_format_artifact(),
            self._config_artifact("local"),
            Artifact(
                _CLAUDE_MD,
                Path(_CLAUDE_MD),
                kind="doc",
                template="CLAUDE.local.md.j2",
                template_root=self._shared_instructions_dir,
                seed_only=True,
            ),
        ]

    def render(self, merged_config: dict[str, Any], *, scope: Scope = "global") -> str:
        """Validate and render merged settings as formatted JSON."""
        validated = (
            self.schema()
            .model_validate(merged_config)
            .model_dump(mode="json", exclude_none=True)
        )
        engine = RenderEngine(self.template_dir)
        return engine.render_template(f"{scope}.j2", {"config": validated})

    def parse_native(self, path: Path) -> dict[str, Any]:
        """Parse a Claude JSON settings file into a plain mapping."""
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"Claude configuration root must be an object: {path}")
        return cast(dict[str, Any], value)

    def template_errors(self) -> list[str]:
        """Return Claude template compilation errors."""
        return [
            *RenderEngine(self.template_dir).validate_templates(),
            *RenderEngine(self._shared_instructions_dir).validate_templates(),
            *self.skill_template_errors(self._skills_dir),
        ]
