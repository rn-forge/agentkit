"""Define the adapter contract used by managers, commands, and discovery.

Concrete adapters declare artifacts and schemas, while the base class resolves
native and staged paths and provides common validation and rendering helpers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ValidationError

from ..core.artifacts import Artifact
from ..core.config import ConfigMerger, MergeResult, defaults_for
from ..core.io import read_config
from ..core.paths import global_root, project_scope_root
from ..core.render import RenderEngine

if TYPE_CHECKING:
    import typer

Scope = Literal["global", "local"]


class AgentAdapter(ABC):
    """Translate agentkit-managed configuration into native agent artifacts.

    Attributes:
        name: Stable adapter identifier used in paths and CLI selection.
        version: Adapter version reported by the version command.
        binary_name: Optional executable checked by the doctor command.
        cli_extension: Optional Typer application mounted below the root CLI.
    """

    name: str
    version = "builtin"
    binary_name: str | None = None
    cli_extension: "typer.Typer | None" = None

    @abstractmethod
    def schema(self) -> type[BaseModel]:
        """Return the Pydantic model for this agent's managed configuration."""

    @abstractmethod
    def render(self, merged_config: dict[str, Any], *, scope: Scope = "global") -> str:
        """Render validated merged configuration to native text.

        Args:
            merged_config: Fully merged configuration mapping.
            scope: Global or repository-local rendering scope.

        Returns:
            Native configuration text for the primary artifact.
        """

    @abstractmethod
    def parse_native(self, path: Path) -> dict[str, Any]:
        """Parse a native file for drift inspection or future capture.

        Args:
            path: Native configuration file to parse.

        Returns:
            Plain configuration values from the native file.

        Raises:
            ValueError: The file is not a valid native configuration.
        """

    @abstractmethod
    def artifacts(self, scope: Scope) -> list[Artifact]:
        """Return every file managed for the requested scope.

        Args:
            scope: Global or repository-local scope.

        Returns:
            Ordered artifact declarations, including exactly one ``config``.
        """

    def validate(self, config: dict[str, Any]) -> list[str]:
        """Return human-readable schema errors for a merged configuration."""
        try:
            self.schema().model_validate(config)
        except ValidationError as exc:
            return [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            ]
        return []

    def defaults(self, scope: Scope) -> dict[str, Any]:
        """Return schema defaults for a scope."""
        return defaults_for(self.schema())

    def read_managed_config(self, path: Path) -> dict[str, Any]:
        """Read an optional agentkit-managed source file."""
        return read_config(path, missing_ok=True)

    def merge(
        self,
        *layers: dict[str, Any] | tuple[str, dict[str, Any]],
    ) -> MergeResult:
        """Merge configuration layers using this adapter's schema strategies."""
        return ConfigMerger(self.schema()).merge(*layers)

    def primary_artifact(self, scope: Scope) -> Artifact:
        """Return the scope's sole primary config artifact.

        Raises:
            ValueError: The adapter does not declare exactly one ``config``.
        """
        primary = [artifact for artifact in self.artifacts(scope) if artifact.key == "config"]
        if len(primary) != 1:
            raise ValueError(
                f"{self.name} must declare exactly one config artifact for {scope}"
            )
        return primary[0]

    def global_native_path(self) -> Path:
        """Return the native global path of the primary config artifact."""
        return self.native_path("global", Path.cwd(), self.primary_artifact("global"))

    def local_native_path(self, repo_root: Path) -> Path:
        """Return the repository-local path of the primary config artifact."""
        return self.native_path("local", repo_root, self.primary_artifact("local"))

    def native_path(
        self, scope: Scope, repo_root: Path, artifact: Artifact | None = None
    ) -> Path:
        """Resolve an artifact's destination beneath its agent or share root."""
        managed = artifact or self.primary_artifact(scope)
        if managed.root == "share":
            root = global_root() if scope == "global" else project_scope_root(repo_root)
        else:
            root = Path.home() if scope == "global" else Path(repo_root)
        return root / managed.native_relative

    def rendered_path(
        self, scope_root: Path, scope: Scope, artifact: Artifact | None = None
    ) -> Path:
        """Resolve an agent-rooted artifact's managed staging path."""
        managed = artifact or self.primary_artifact(scope)
        return (
            Path(scope_root)
            / self.name
            / "rendered"
            / managed.native_relative
        )

    def render_artifact(
        self, artifact: Artifact, merged_config: dict[str, Any], scope: Scope
    ) -> str | bytes:
        """Render a template artifact or read a packaged static artifact.

        Raises:
            ValueError: A non-primary template cannot be located or rendered.
        """
        if artifact.source is not None:
            return artifact.source.read_bytes()
        if artifact.key == "config":
            return self.render(merged_config, scope=scope)
        template_dir = getattr(self, "template_dir", None)
        if not isinstance(template_dir, Path) or artifact.template is None:
            raise ValueError(f"Cannot render templated artifact: {artifact.key}")
        return RenderEngine(template_dir).render_template(
            artifact.template, {"config": merged_config}
        )

    def template_errors(self) -> list[str]:
        """Return template compilation errors, if the adapter uses templates."""
        return []
