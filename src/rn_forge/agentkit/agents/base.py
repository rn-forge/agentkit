"""Define the adapter contract used by managers, commands, and discovery.

Concrete adapters declare artifacts and schemas, while the base class resolves native
and staged paths and provides common validation and rendering helpers.
"""

from __future__ import annotations

import inspect
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

_MANAGED_SOURCE_HEADER = """\
# agentkit managed source — {agent}, {scope} scope.
#
# Keys set here override the packaged {scope} defaults and are merged into every
# rendered {agent} artifact. This file is the layer you edit by hand; it is also
# where `agentkit diff --scope {scope} --write` captures native changes.
#
# An empty file means "no {scope} overrides" — the packaged defaults apply as-is.
"""


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
    _defaults_suffix: str | None = None
    """Extension of the packaged scope-defaults file (``.json``, ``.toml``, ...).

    ``None`` means this adapter's defaults are schema-only, with nothing packaged to
    merge or promote into.
    """

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
    def _global_artifacts(self) -> list[Artifact]:
        """Return every file managed for the global scope, in declaration order."""

    @abstractmethod
    def _local_artifacts(self) -> list[Artifact]:
        """Return every file managed for the local scope, in declaration order."""

    def artifacts(self, scope: Scope) -> list[Artifact]:
        """Return every file managed for the requested scope.

        Args:
            scope: Global or repository-local scope.

        Returns:
            Ordered artifact declarations, including exactly one ``config``.
        """
        return (
            self._global_artifacts() if scope == "global" else self._local_artifacts()
        )

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
        """Return schema defaults merged with any packaged scope defaults."""
        schema_defaults = defaults_for(self.schema())
        path = self.defaults_path(scope)
        if path is None or not path.exists():
            return schema_defaults
        return (
            ConfigMerger(self.schema()).merge(schema_defaults, read_config(path)).config
        )

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
        <rn_forge.agentkit.core.operations.capture.capture_assets>`. ``None`` means this
        adapter's defaults are schema-only, with nothing packaged to promote into.
        """
        if self._defaults_suffix is None:
            return None
        return self.package_dir / "defaults" / f"{scope}{self._defaults_suffix}"

    def managed_source_scaffold(self, scope: Scope) -> str:
        """Return the documented empty-override scaffold for this adapter and scope."""
        return _MANAGED_SOURCE_HEADER.format(agent=self.name, scope=scope)

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
    def package_dir(self) -> Path:
        """Return the packaged directory containing this adapter's own module.

        Uses ``inspect`` rather than ``__file__`` because the base class cannot use its
        own ``__file__`` to find a *subclass's* package directory — this works for
        third-party adapters too.
        """
        return Path(inspect.getfile(type(self))).parent

    @property
    def template_dir(self) -> Path:
        """Return the packaged Jinja template directory for this adapter."""
        return self.package_dir / "templates"

    @property
    def _assets_dir(self) -> Path:
        return self.package_dir / "assets"

    @property
    def _shared_scripts_dir(self) -> Path:
        return Path(__file__).parents[1] / "assets" / "scripts"

    @property
    def _shared_instructions_dir(self) -> Path:
        return Path(__file__).parents[1] / "assets" / "instructions"

    @property
    def shared_skills_dir(self) -> Path:
        """Return the packaged agent-neutral skill source tree."""
        return Path(__file__).parents[1] / "assets" / "skills"

    @property
    def _skills_dir(self) -> Path:
        """Return this adapter's native skills root, e.g. ``.claude/skills``."""
        return Path(f".{self.name}") / "skills"

    def _guard_core_artifact(self) -> Artifact:
        """Declare the guard script every adapter's hooks depend on."""
        return Artifact(
            "hooks/guard-core.sh",
            Path("_common/hooks/guard-core.sh"),
            kind="hook",
            root="share",
            source=self._shared_scripts_dir / "guard-core.sh",
        )

    def _hook_script_artifacts(self, names: tuple[str, ...]) -> list[Artifact]:
        """Declare packaged, per-agent executable hook scripts by filename."""
        return [
            Artifact(
                f"hooks/{name}",
                Path(self.name) / "hooks" / name,
                kind="hook",
                root="share",
                source=self._assets_dir / "hooks" / name,
                executable=True,
            )
            for name in names
        ]

    def _post_edit_format_artifact(self) -> Artifact:
        """Declare the local-scope post-edit formatting hook script."""
        return Artifact(
            key="hooks/post-edit-format.sh",
            native_relative=Path(self.name) / "hooks" / "post-edit-format.sh",
            kind="hook",
            root="share",
            source=self._shared_scripts_dir / "post-edit-format.sh",
            executable=True,
        )

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
                        template_root=root,
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
        errors: list[str] = []
        for artifact in self.skill_artifacts(native_skills_dir):
            if artifact.template is None:
                continue
            try:
                self.render_skill_artifact(artifact)
            except RenderError as exc:
                errors.append(f"{artifact.template}: {exc}")
        return errors

    def _render_context(
        self, artifact: Artifact, merged_config: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the Jinja context for a templated artifact, keyed by ``kind``."""
        if artifact.kind == "skill":
            return {"agent": self.name}
        if artifact.kind == "doc":
            return {}
        return {"config": merged_config}

    def render_artifact(
        self, artifact: Artifact, merged_config: dict[str, Any], scope: Scope
    ) -> str | bytes:
        """Render a template artifact or read a packaged static artifact."""
        if artifact.source is not None:
            return artifact.source.read_bytes()
        if artifact.key == "config":
            return self.render(merged_config, scope=scope)
        assert artifact.template is not None
        root = artifact.template_root or self.template_dir
        return RenderEngine(root).render_template(
            artifact.template, self._render_context(artifact, merged_config)
        )

    def source_path(self, artifact: Artifact) -> Path | None:
        """Return the packaged file an artifact's content is produced from.

        For a static artifact this is the copied file; for a templated one, the
        template. The primary ``config`` artifact resolves to its template too, even
        though the *values* come from the merged layer chain — use ``agentkit diff`` to
        see those.
        """
        if artifact.source is not None:
            return artifact.source
        if artifact.template is None:
            return None
        return (artifact.template_root or self.template_dir) / artifact.template

    def template_errors(self) -> list[str]:
        """Return template compilation errors, if the adapter uses templates."""
        return []
