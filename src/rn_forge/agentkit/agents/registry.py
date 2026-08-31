"""Combine built-in adapters with integrations discovered by entry point.

CLI selection and doctor checks share the process-wide :data:`registry`.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from .base import AgentAdapter


class AgentRegistry:
    """Discover and address adapters by stable agent name."""

    entry_point_group = "agentkit.adapters"

    def __init__(self) -> None:
        """Create an empty lazy discovery cache."""
        self._adapters: dict[str, AgentAdapter] | None = None

    def discover(self, *, refresh: bool = False) -> list[AgentAdapter]:
        """Return built-in and installed adapters in stable name order.

        Args:
            refresh: Rebuild the entry-point cache when true.

        Raises:
            TypeError: An entry point does not produce an ``AgentAdapter``.
        """
        if self._adapters is not None and not refresh:
            return list(self._adapters.values())

        from .claude import ClaudeAdapter
        from .codex import CodexAdapter

        adapters: dict[str, AgentAdapter] = {
            "claude": ClaudeAdapter(),
            "codex": CodexAdapter(),
        }
        for point in entry_points(group=self.entry_point_group):
            loaded: Any = point.load()
            adapter = (
                loaded() if isinstance(loaded, type) or callable(loaded) else loaded
            )
            if not isinstance(adapter, AgentAdapter):
                raise TypeError(f"Entry point {point.name!r} is not an AgentAdapter")
            adapters[adapter.name] = adapter
        self._adapters = dict(sorted(adapters.items()))
        return list(self._adapters.values())

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
