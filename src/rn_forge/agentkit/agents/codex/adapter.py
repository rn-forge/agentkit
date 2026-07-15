"""Codex TOML configuration adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.io import read_config
from ...core.render import RenderEngine
from ..base import AgentAdapter, Scope
from .schema import CodexConfig


class CodexAdapter(AgentAdapter):
    name = "codex"
    binary_name = "codex"

    def __init__(self) -> None:
        self.template_dir = Path(__file__).parent / "templates"

    def schema(self) -> type[CodexConfig]:
        return CodexConfig

    def global_native_path(self) -> Path:
        return Path.home() / ".codex" / "config.toml"

    def local_native_path(self, repo_root: Path) -> Path:
        return Path(repo_root) / ".codex" / "config.toml"

    def rendered_relative_path(self, scope: Scope) -> Path:
        return Path(".codex") / "config.toml"

    def render(self, merged_config: dict[str, Any], *, scope: Scope = "global") -> str:
        validated = (
            self.schema()
            .model_validate(merged_config)
            .model_dump(mode="python", exclude_none=True)
        )
        return RenderEngine(self.template_dir).render_template(
            f"{scope}.j2", {"config": validated}
        )

    def parse_native(self, path: Path) -> dict[str, Any]:
        return read_config(path)

    def template_errors(self) -> list[str]:
        return RenderEngine(self.template_dir).validate_templates()
