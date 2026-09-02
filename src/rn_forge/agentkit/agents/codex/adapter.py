"""Implement Codex TOML rendering and default-pack artifacts.

The adapter combines the Codex schema, packaged scope defaults, Jinja TOML templates,
native ``.codex`` paths, and shared hooks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.artifacts import Artifact
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
    _defaults_suffix = ".toml"

    def schema(self) -> type[CodexConfig]:
        """Return the Codex configuration schema."""
        return CodexConfig

    def _config_artifact(self, scope: Scope) -> Artifact:
        return Artifact(
            key="config",
            native_relative=Path(".codex") / "config.toml",
            template=f"{scope}.j2",
        )

    def _global_artifacts(self) -> list[Artifact]:
        """Declare Codex config, instruction, and hook artifacts."""
        # `hooks.json` is declared after the shared hook scripts it points at
        # by path, so a written `hooks.json` never lands pointing at a script
        # that does not exist yet.
        return [
            self._guard_core_artifact(),
            *self._hook_script_artifacts(
                (
                    "pre-bash-guard.sh",
                    "user-prompt-secret-guard.sh",
                    "pre-write-protect.sh",
                )
            ),
            Artifact(
                _HOOKS_JSON,
                Path(".codex/hooks.json"),
                source=self._assets_dir / _HOOKS_JSON,
            ),
            self._config_artifact("global"),
            Artifact(
                _AGENTS_MD,
                Path(".codex/AGENTS.md"),
                kind="doc",
                template="AGENTS.md.j2",
                template_root=self._shared_instructions_dir,
            ),
            *self.skill_artifacts(self._skills_dir),
        ]

    def _local_artifacts(self) -> list[Artifact]:
        """Declare Codex local-scope config, instruction seed, and hook artifacts."""
        return [
            self._post_edit_format_artifact(),
            Artifact(
                _HOOKS_JSON,
                Path(".codex/hooks.json"),
                source=self._assets_dir / "hooks.local.json",
            ),
            self._config_artifact("local"),
            Artifact(
                _AGENTS_MD,
                Path(_AGENTS_MD),
                kind="doc",
                template="AGENTS.local.md.j2",
                template_root=self._shared_instructions_dir,
                seed_only=True,
            ),
        ]

    def is_native_hook_artifact(self, artifact: Artifact) -> bool:
        """Identify ``hooks.json``, whose entire content is hook registration."""
        return artifact.key == _HOOKS_JSON

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
        return [
            *RenderEngine(self.template_dir).validate_templates(),
            *RenderEngine(self._shared_instructions_dir).validate_templates(),
            *self.skill_template_errors(self._skills_dir),
        ]
