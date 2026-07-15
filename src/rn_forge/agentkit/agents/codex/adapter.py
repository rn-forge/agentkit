"""Implement Codex TOML rendering and default-pack artifacts.

The adapter combines the Codex schema, packaged scope defaults, Jinja TOML
templates, native ``.codex`` paths, shared hooks, and a bundled skill.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.artifacts import Artifact
from ...core.config import ConfigMerger, defaults_for
from ...core.io import read_config
from ...core.render import RenderEngine
from ..base import AgentAdapter, Scope
from .schema import CodexConfig


class CodexAdapter(AgentAdapter):
    """Manage Codex global and repository-local configuration files."""

    name = "codex"
    binary_name = "codex"

    def __init__(self) -> None:
        """Initialize the packaged template directory."""
        self.template_dir = Path(__file__).parent / "templates"

    def schema(self) -> type[CodexConfig]:
        """Return the Codex configuration schema."""
        return CodexConfig

    def artifacts(self, scope: Scope) -> list[Artifact]:
        """Declare Codex config, instruction, hook, and skill artifacts."""
        config = Artifact(
            key="config",
            native_relative=Path(".codex") / "config.toml",
            template=f"{scope}.j2",
        )
        if scope == "local":
            return [config]
        return [
            config,
            Artifact(
                "AGENTS.md",
                Path(".codex/AGENTS.md"),
                source=self._assets_dir / "AGENTS.md",
            ),
            Artifact(
                "hooks.json",
                Path(".codex/hooks.json"),
                source=self._assets_dir / "hooks.json",
            ),
            Artifact(
                "hooks/lib/guard-core.sh",
                Path("hooks/lib/guard-core.sh"),
                root="share",
                source=self._shared_scripts_dir / "guard-core.sh",
            ),
            *[
                Artifact(
                    f"hooks/{name}",
                    Path("hooks/codex") / name,
                    root="share",
                    source=self._assets_dir / "hooks" / name,
                    executable=True,
                )
                for name in (
                    "pre-bash-guard.sh",
                    "user-prompt-secret-guard.sh",
                )
            ],
            Artifact(
                "skills/repo-context/SKILL.md",
                Path(".codex/skills/repo-context/SKILL.md"),
                source=self._assets_dir / "skills/repo-context/SKILL.md",
            ),
            Artifact(
                "skills/repo-context/agents/openai.yaml",
                Path(".codex/skills/repo-context/agents/openai.yaml"),
                source=self._assets_dir
                / "skills/repo-context/agents/openai.yaml",
            ),
        ]

    @property
    def _assets_dir(self) -> Path:
        return Path(__file__).parent / "assets"

    @property
    def _shared_scripts_dir(self) -> Path:
        return Path(__file__).parents[2] / "assets" / "scripts"

    def defaults(self, scope: Scope) -> dict[str, Any]:
        """Merge schema defaults with the packaged Codex scope defaults."""
        packaged = read_config(Path(__file__).parent / "defaults" / f"{scope}.toml")
        return ConfigMerger(self.schema()).merge(
            defaults_for(self.schema()), packaged
        ).config

    def render(self, merged_config: dict[str, Any], *, scope: Scope = "global") -> str:
        """Validate and render merged configuration as TOML."""
        validated = (
            self.schema()
            .model_validate(merged_config)
            .model_dump(mode="python", exclude_none=True)
        )
        return RenderEngine(self.template_dir).render_template(
            f"{scope}.j2", {"config": validated}
        )

    def parse_native(self, path: Path) -> dict[str, Any]:
        """Parse a Codex TOML file into a plain mapping."""
        return read_config(path)

    def template_errors(self) -> list[str]:
        """Return Codex template compilation errors."""
        return RenderEngine(self.template_dir).validate_templates()
