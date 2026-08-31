"""Implement Codex TOML rendering and default-pack artifacts.

The adapter combines the Codex schema, packaged scope defaults, Jinja TOML
templates, native ``.codex`` paths, and shared hooks.
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


_AGENTS_MD = "AGENTS.md"
_HOOKS_JSON = "hooks.json"


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
        """Declare Codex config, instruction, and hook artifacts."""
        config = Artifact(
            key="config",
            native_relative=Path(".codex") / "config.toml",
            template=f"{scope}.j2",
        )
        if scope == "local":
            return [
                config,
                Artifact(
                    _AGENTS_MD,
                    Path(_AGENTS_MD),
                    template="AGENTS.local.md.j2",
                    seed_only=True,
                ),
                Artifact(
                    _HOOKS_JSON,
                    Path(".codex/hooks.json"),
                    source=self._assets_dir / "hooks.local.json",
                ),
                Artifact(
                    key="hooks/post-edit-format.sh",
                    native_relative=Path("codex/hooks/post-edit-format.sh"),
                    root="share",
                    source=self._shared_scripts_dir / "post-edit-format.sh",
                    executable=True,
                ),
            ]
        return [
            config,
            Artifact(
                _AGENTS_MD,
                Path(".codex/AGENTS.md"),
                template="AGENTS.md.j2",
            ),
            Artifact(
                _HOOKS_JSON,
                Path(".codex/hooks.json"),
                source=self._assets_dir / _HOOKS_JSON,
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
                    Path("codex/hooks") / name,
                    root="share",
                    source=self._assets_dir / "hooks" / name,
                    executable=True,
                )
                for name in (
                    "pre-bash-guard.sh",
                    "user-prompt-secret-guard.sh",
                    "pre-write-protect.sh",
                )
            ],
            Artifact(
                "hooks/post-write-unwrap-md.sh",
                Path("codex/hooks/post-write-unwrap-md.sh"),
                root="share",
                source=self._shared_scripts_dir / "post-write-unwrap-md.sh",
                executable=True,
            ),
            Artifact(
                "hooks/unwrap_md.py",
                Path("codex/hooks/unwrap_md.py"),
                root="share",
                source=self._shared_scripts_dir / "unwrap_md.py",
            ),
            *self.skill_artifacts(self._skills_dir),
        ]

    _skills_dir = Path(".codex/skills")

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
        """Merge schema defaults with the packaged Codex scope defaults."""
        packaged = read_config(Path(__file__).parent / "defaults" / f"{scope}.toml")
        return (
            ConfigMerger(self.schema())
            .merge(defaults_for(self.schema()), packaged)
            .config
        )

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

    def render_artifact(
        self, artifact: Artifact, merged_config: dict[str, Any], scope: Scope
    ) -> str | bytes:
        """Render shared instruction templates and delegate other artifacts."""
        if artifact.key.startswith("skills/") and artifact.template is not None:
            return self.render_skill_artifact(artifact)
        if artifact.key == _AGENTS_MD:
            assert artifact.template is not None
            return RenderEngine(self._shared_instructions_dir).render_template(
                artifact.template, {}
            )
        return super().render_artifact(artifact, merged_config, scope)

    def template_errors(self) -> list[str]:
        """Return Codex template compilation errors."""
        return [
            *RenderEngine(self.template_dir).validate_templates(),
            *RenderEngine(self._shared_instructions_dir).validate_templates(),
            *self.skill_template_errors(self._skills_dir),
        ]
