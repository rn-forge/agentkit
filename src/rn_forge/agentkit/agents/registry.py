"""Combine built-in adapters with integrations discovered by entry point.

CLI selection and doctor checks share the process-wide :data:`registry`.

Third-party adapters are loaded from installed entry points, which means an unrelated
package can break this process at import time. Discovery therefore isolates each entry
point: one broken plugin is recorded in :attr:`AgentRegistry.errors` and skipped, so
``--help``, ``version``, and every other agent keep working. ``doctor`` surfaces those
errors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from .base import AgentAdapter, Scope

_VALID_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
"""Adapter names become path segments, so they must be safe and unsurprising."""

@dataclass(frozen=True, slots=True)
class PluginError:
    """One entry point that could not be turned into a usable adapter."""

    entry_point: str
    reason: str


class AgentRegistry:
    """Discover and address adapters by stable agent name."""

    entry_point_group = "agentkit.adapters"

    def __init__(self) -> None:
        """Create an empty lazy discovery cache."""
        self._adapters: dict[str, AgentAdapter] | None = None
        self._errors: list[PluginError] = []

    @property
    def errors(self) -> list[PluginError]:
        """Return plugin failures from the most recent discovery."""
        self.discover()
        return list(self._errors)

    def discover(self, *, refresh: bool = False) -> list[AgentAdapter]:
        """Return built-in and installed adapters in stable name order.

        A failing entry point never propagates: it is collected into
        :attr:`errors` and skipped, because a third-party import error must not
        take down the whole CLI.

        Args:
            refresh: Rebuild the entry-point cache when true.
        """
        if self._adapters is not None and not refresh:
            return list(self._adapters.values())

        from .claude import ClaudeAdapter
        from .codex import CodexAdapter

        builtins: dict[str, AgentAdapter] = {
            "claude": ClaudeAdapter(),
            "codex": CodexAdapter(),
        }
        adapters = dict(builtins)
        errors: list[PluginError] = []
        # Sort by entry-point name so discovery order — and therefore any
        # ordering-dependent behaviour — does not depend on install order.
        for point in sorted(
            entry_points(group=self.entry_point_group), key=lambda item: item.name
        ):
            try:
                adapter = self._load(point, builtins, adapters)
            except Exception as exc:  # noqa: BLE001 - one plugin must not break all
                errors.append(PluginError(point.name, f"{type(exc).__name__}: {exc}"))
                continue
            adapters[adapter.name] = adapter

        self._adapters = dict(sorted(adapters.items()))
        self._errors = errors
        return list(self._adapters.values())

    def _load(
        self,
        point: EntryPoint,
        builtins: dict[str, AgentAdapter],
        seen: dict[str, AgentAdapter],
    ) -> AgentAdapter:
        """Load and validate one entry point.

        Raises:
            TypeError: The entry point does not produce an ``AgentAdapter``.
            ValueError: The adapter name is unusable or already taken.
        """
        loaded: Any = point.load()
        adapter = loaded() if isinstance(loaded, type) or callable(loaded) else loaded
        if not isinstance(adapter, AgentAdapter):
            raise TypeError(f"{point.value} is not an AgentAdapter")
        # A non-string name raises from `match` and is caught by discover(),
        # which reports it as a plugin error rather than crashing the CLI.
        name = adapter.name
        if not _VALID_NAME.match(name):
            raise ValueError(
                f"adapter name {name!r} must match {_VALID_NAME.pattern} "
                "(it is used as a directory name)"
            )
        if name in builtins:
            raise ValueError(f"adapter name {name!r} is reserved by a built-in adapter")
        if name in seen and name not in builtins:
            raise ValueError(f"adapter name {name!r} is already registered")
        self._validate_artifacts(adapter)
        return adapter

    @staticmethod
    def _validate_artifacts(adapter: AgentAdapter) -> None:
        """Reject artifact sets whose keys or destinations are ambiguous.

        ``Artifact`` validates each declaration on its own; only the adapter can see
        that two of them collide. Duplicate keys make state records ambiguous and
        duplicate destinations make the last write silently win.

        Raises:
            ValueError: Keys or native destinations collide within a scope, or a
                scope does not declare exactly one ``config`` artifact.
        """
        scopes: tuple[Scope, ...] = ("global", "local")
        for scope in scopes:
            artifacts = adapter.artifacts(scope)
            keys = [artifact.key for artifact in artifacts]
            if len(keys) != len(set(keys)):
                duplicates = sorted({key for key in keys if keys.count(key) > 1})
                raise ValueError(
                    f"duplicate artifact keys in {scope} scope: {duplicates}"
                )
            destinations = [
                (artifact.root, artifact.native_relative) for artifact in artifacts
            ]
            if len(destinations) != len(set(destinations)):
                raise ValueError(f"duplicate artifact destinations in {scope} scope")
            # `AgentAdapter.primary_artifact()` assumes exactly one `config` key
            # and raises only when a caller reaches it (apply, status, doctor);
            # checking it here means a plugin that violates the contract is
            # rejected at discovery, not partway through some later command.
            primary_count = sum(1 for key in keys if key == "config")
            if primary_count != 1:
                raise ValueError(
                    f"{scope} scope must declare exactly one 'config' artifact, "
                    f"found {primary_count}"
                )

    def get(self, name: str) -> AgentAdapter:
        """Return one adapter by name.

        Raises:
            KeyError: The requested adapter is not installed.
        """
        adapters = {adapter.name: adapter for adapter in self.discover()}
        try:
            return adapters[name]
        except KeyError as exc:
            choices = ", ".join(adapters)
            raise KeyError(f"Unknown agent {name!r}; choose from: {choices}") from exc

    def select(self, names: list[str] | None) -> list[AgentAdapter]:
        """Return named adapters, or all discovered adapters when omitted."""
        return self.discover() if not names else [self.get(name) for name in names]


registry = AgentRegistry()
