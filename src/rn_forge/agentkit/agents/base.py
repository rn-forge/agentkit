"""Define the adapter contract used by managers, commands, and discovery.

Concrete adapters declare artifacts and schemas, while the base class resolves native
and staged paths and provides common validation and rendering helpers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ValidationError

from ..core.artifacts import Artifact
from ..core.config import ConfigMerger, MergeResult, defaults_for
from ..core.io import loads_config, read_config
from ..core.paths import global_root, project_scope_root
from ..core.render import RenderEngine, RenderError

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

    def parse_native_text(self, text: str, artifact: Artifact) -> dict[str, Any]:
        """Parse rendered native text using an artifact's on-disk format.

        The staged copy of a rendered artifact is disposable, so callers that
        need the *expected* native mapping render it in memory and parse it
        here instead of reading ``rendered/``.

        Raises:
            ValueError: The text is not a valid mapping-rooted native config.
        """
        return loads_config(text, Path(artifact.native_relative).suffix.lstrip("."))

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

    def is_native_hook_artifact(self, artifact: Artifact) -> bool:
        """Report whether an artifact's entire native content is hook wiring.

        The primary ``config`` artifact usually mixes hook registrations with settings
        that stay meaningful without agentkit (Claude's ``permissions.deny``,
        ``outputStyle``) — uninstall edits it in place rather than deleting it. Some
        adapters also declare a separate, statically-sourced artifact that exists solely
        to register hooks (Codex's ``hooks.json``): unlike the primary config, deleting
        it outright loses nothing else, so uninstall's file cleanup removes it alongside
        skills rather than trying to edit it. ``False`` by default; an adapter with such
        an artifact overrides this to identify it by key.
        """
        return False

    def defaults_path(self, scope: Scope) -> Path | None:
        """Return the packaged scope-defaults file :meth:`defaults` reads from, if any.

        Exposed so capture can promote a managed override into the file that ships as
        everyone's default, mirroring how ``Artifact.source`` exposes a static
        artifact's packaged source to :func:`capture_assets
        <rn_forge.agentkit.core.manager.capture_assets>`. ``None`` means this adapter's
        defaults are schema-only, with nothing packaged to promote into.
        """
        return None

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
        primary = [
            artifact for artifact in self.artifacts(scope) if artifact.key == "config"
        ]
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
        return Path(scope_root) / self.name / "rendered" / managed.native_relative

    @property
    def shared_skills_dir(self) -> Path:
        """Return the packaged agent-neutral skill source tree."""
        return Path(__file__).parents[1] / "assets" / "skills"

    def skill_artifacts(self, native_skills_dir: Path) -> list[Artifact]:
        """Declare every packaged skill file beneath an agent's skills root.

        ``SKILL.md.j2`` files render per agent so the handful of harness-specific
        lines can branch on ``agent``; every other file is a bundled resource
        copied verbatim, because template placeholders inside them (go-task's
        ``{{.VAR}}``, GitHub Actions' ``${{ }}``) are not Jinja and must survive
        untouched.

        Args:
            native_skills_dir: Skills root relative to the agent's native root.
        """
        root = self.shared_skills_dir
        artifacts: list[Artifact] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if path.suffix == ".j2":
                rendered = relative.with_suffix("")
                artifacts.append(
                    Artifact(
                        key=f"skills/{rendered.as_posix()}",
                        native_relative=native_skills_dir / rendered,
                        kind="skill",
                        template=relative.as_posix(),
                    )
                )
            else:
                artifacts.append(
                    Artifact(
                        key=f"skills/{relative.as_posix()}",
                        native_relative=native_skills_dir / relative,
                        kind="skill",
                        source=path,
                    )
                )
        return artifacts

    def render_skill_artifact(self, artifact: Artifact) -> str:
        """Render one skill template for this agent."""
        assert artifact.template is not None
        return RenderEngine(self.shared_skills_dir).render_template(
            artifact.template, {"agent": self.name}
        )

    def skill_template_errors(self, native_skills_dir: Path) -> list[str]:
        """Return render errors for every packaged skill template.

        Rendering rather than merely compiling is deliberate: it also catches an
        undefined variable under ``StrictUndefined``.
        """
        engine = RenderEngine(self.shared_skills_dir)
        errors: list[str] = []
        for artifact in self.skill_artifacts(native_skills_dir):
            if artifact.template is None:
                continue
            try:
                engine.render_template(artifact.template, {"agent": self.name})
            except RenderError as exc:
                errors.append(f"{artifact.template}: {exc}")
        return errors

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
        if artifact.template is None:
            raise ValueError(f"Cannot render templated artifact: {artifact.key}")
        return RenderEngine(self.template_root(artifact)).render_template(
            artifact.template, {"config": merged_config}
        )

    def template_root(self, artifact: Artifact) -> Path:
        """Return the packaged directory ``artifact.template`` is resolved against.

        Adapters that render some artifacts from a directory other than
        ``template_dir`` override this rather than only :meth:`render_artifact`,
        so ``doctor`` can name a template artifact's source file without
        re-deriving the same dispatch a second time and drifting from it.

        Raises:
            ValueError: The adapter declares no template directory.
        """
        template_dir = getattr(self, "template_dir", None)
        if not isinstance(template_dir, Path):
            raise ValueError(f"Cannot render templated artifact: {artifact.key}")
        return template_dir

    def source_path(self, artifact: Artifact) -> Path | None:
        """Return the packaged file an artifact's content is produced from.

        For a static artifact this is the copied file; for a templated one, the
        template. The primary ``config`` artifact resolves to its template too,
        even though the *values* come from the merged layer chain — use
        ``agentkit diff`` to see those.

        Returns:
            An absolute packaged path, or ``None`` when the adapter declares no
            template directory to resolve the template against.
        """
        if artifact.source is not None:
            return artifact.source
        if artifact.template is None:
            return None
        try:
            return self.template_root(artifact) / artifact.template
        except ValueError:
            return None

    def template_errors(self) -> list[str]:
        """Return template compilation errors, if the adapter uses templates."""
        return []
