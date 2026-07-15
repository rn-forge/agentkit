"""Claude Code JSON settings adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...core.render import RenderEngine
from ..base import AgentAdapter, Scope
from .schema import ClaudeConfig


class ClaudeAdapter(AgentAdapter):
    name = "claude"
    binary_name = "claude"

    def __init__(self) -> None:
        self.template_dir = Path(__file__).parent / "templates"

    def schema(self) -> type[ClaudeConfig]:
        return ClaudeConfig

    def global_native_path(self) -> Path:
        return Path.home() / ".claude" / "settings.json"

    def local_native_path(self, repo_root: Path) -> Path:
        return Path(repo_root) / ".claude" / "settings.local.json"

    def rendered_relative_path(self, scope: Scope) -> Path:
        filename = "settings.json" if scope == "global" else "settings.local.json"
        return Path(".claude") / filename

    def render(self, merged_config: dict[str, Any], *, scope: Scope = "global") -> str:
        validated = (
            self.schema()
            .model_validate(merged_config)
            .model_dump(mode="json", exclude_none=True)
        )
        engine = RenderEngine(self.template_dir)
        return engine.render_template(f"{scope}.j2", {"config": validated})

    def parse_native(self, path: Path) -> dict[str, Any]:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"Claude configuration root must be an object: {path}")
        return value

    def template_errors(self) -> list[str]:
        return RenderEngine(self.template_dir).validate_templates()
