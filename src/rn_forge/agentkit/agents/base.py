"""Plugin interface implemented by every supported coding agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ValidationError

from ..core.config import ConfigMerger, defaults_for
from ..core.io import read_config

if TYPE_CHECKING:
    import typer

Scope = Literal["global", "local"]


class AgentAdapter(ABC):
    """Translate agentkit-managed config into an agent's native format."""

    name: str
    version = "builtin"
    binary_name: str | None = None
    cli_extension: "typer.Typer | None" = None

    @abstractmethod
    def schema(self) -> type[BaseModel]:
        """Return the Pydantic model for this agent's managed configuration."""

    @abstractmethod
    def global_native_path(self) -> Path:
        """Return the native global configuration path."""

    @abstractmethod
    def local_native_path(self, repo_root: Path) -> Path:
        """Return the native project configuration path."""

    @abstractmethod
    def render(self, merged_config: dict[str, Any], *, scope: Scope = "global") -> str:
        """Render validated merged configuration to native text."""

    @abstractmethod
    def parse_native(self, path: Path) -> dict[str, Any]:
        """Parse a native file for drift inspection or future import support."""

    @abstractmethod
    def rendered_relative_path(self, scope: Scope) -> Path:
        """Return the native path represented beneath the rendered directory."""

    def validate(self, config: dict[str, Any]) -> list[str]:
        try:
            self.schema().model_validate(config)
        except ValidationError as exc:
            return [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            ]
        return []

    def defaults(self) -> dict[str, Any]:
        return defaults_for(self.schema())

    def read_managed_config(self, path: Path) -> dict[str, Any]:
        return read_config(path, missing_ok=True)

    def merge(
        self,
        *layers: dict[str, Any] | tuple[str, dict[str, Any]],
    ):
        return ConfigMerger(self.schema()).merge(*layers)

    def native_path(self, scope: Scope, repo_root: Path) -> Path:
        return (
            self.global_native_path()
            if scope == "global"
            else self.local_native_path(repo_root)
        )

    def rendered_path(self, scope_root: Path, scope: Scope) -> Path:
        return (
            Path(scope_root)
            / self.name
            / "rendered"
            / self.rendered_relative_path(scope)
        )

    def template_errors(self) -> list[str]:
        return []
