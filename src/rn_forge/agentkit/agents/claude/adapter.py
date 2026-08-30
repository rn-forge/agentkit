"""Implement Claude Code JSON rendering and default-pack artifacts.

The adapter combines the Claude schema, packaged scope defaults, Jinja JSON
templates, native ``.claude`` paths, and shared hook assets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ...core.artifacts import Artifact
from ...core.config import ConfigMerger, defaults_for
from ...core.io import read_config
from ...core.render import RenderEngine
from ..base import AgentAdapter, Scope
from .schema import ClaudeConfig


class ClaudeAdapter(AgentAdapter):
    """Manage Claude Code global and repository-local configuration files."""

    name = "claude"
    binary_name = "claude"

    def __init__(self) -> None:
        """Initialize the packaged template directory."""
        self.template_dir = Path(__file__).parent / "templates"

    def schema(self) -> type[ClaudeConfig]:
        """Return the Claude settings schema."""
        return ClaudeConfig

    def artifacts(self, scope: Scope) -> list[Artifact]:
        """Declare Claude config, instruction, style, and hook artifacts."""
        filename = "settings.json" if scope == "global" else "settings.local.json"
        config = Artifact(
            key="config",
            native_relative=Path(".claude") / filename,
            template=f"{scope}.j2",
        )
        if scope == "local":
            return [
                config,
                Artifact(
                    "CLAUDE.md",
                    Path("CLAUDE.md"),
                    template="CLAUDE.local.md.j2",
                    seed_only=True,
                ),
                Artifact(
                    key="hooks/post-edit-format.sh",
                    native_relative=Path("claude/hooks/post-edit-format.sh"),
                    root="share",
                    source=self._shared_scripts_dir / "post-edit-format.sh",
                    executable=True,
                ),
            ]
        return [
            config,
            Artifact(
                "CLAUDE.md",
                Path(".claude/CLAUDE.md"),
                template="CLAUDE.md.j2",
            ),
            Artifact(
                "output-styles/concise.md",
                Path(".claude/output-styles/concise.md"),
                template="concise.md.j2",
            ),
            Artifact(
                "hooks/guard-core.sh",
                Path("_common/hooks/guard-core.sh"),
                root="share",
                source=self._shared_scripts_dir / "guard-core.sh",
            ),
            *[
                Artifact(
                    f"hooks/{name}",
                    Path("claude/hooks") / name,
                    root="share",
                    source=self._assets_dir / "hooks" / name,
                    executable=True,
                )
                for name in (
                    "pre-bash-guard.sh",
                    "user-prompt-secret-guard.sh",
                    "pre-write-protect.sh",
                    "session-compact-context.sh",
                )
            ],
            *self.skill_artifacts(self._skills_dir),
        ]

    _skills_dir = Path(".claude/skills")

    @property
    def _assets_dir(self) -> Path:
        return Path(__file__).parent / "assets"

    @property
    def _shared_scripts_dir(self) -> Path:
        return Path(__file__).parents[2] / "assets" / "scripts"

    @property
    def _shared_instructions_dir(self) -> Path:
        return Path(__file__).parents[2] / "assets" / "instructions"

    def defaults(self, scope: Scope) -> dict[str, Any]:
        """Merge schema defaults with the packaged Claude scope defaults."""
        packaged = read_config(Path(__file__).parent / "defaults" / f"{scope}.json")
        return (
            ConfigMerger(self.schema())
            .merge(defaults_for(self.schema()), packaged)
            .config
        )

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

    def render_artifact(
        self, artifact: Artifact, merged_config: dict[str, Any], scope: Scope
    ) -> str | bytes:
        """Render shared instruction templates and delegate other artifacts."""
        if artifact.key.startswith("skills/") and artifact.template is not None:
            return self.render_skill_artifact(artifact)
        if artifact.key in {"CLAUDE.md", "output-styles/concise.md"}:
            assert artifact.template is not None
            return RenderEngine(self._shared_instructions_dir).render_template(
                artifact.template, {}
            )
        return super().render_artifact(artifact, merged_config, scope)

    def template_errors(self) -> list[str]:
        """Return Claude template compilation errors."""
        return [
            *RenderEngine(self.template_dir).validate_templates(),
            *RenderEngine(self._shared_instructions_dir).validate_templates(),
            *self.skill_template_errors(self._skills_dir),
        ]
