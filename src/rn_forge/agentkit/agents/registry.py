"""Built-in registration and entry-point discovery for adapters."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from .base import AgentAdapter


class AgentRegistry:
    """Discover and address adapters by stable agent name."""

    entry_point_group = "agentkit.adapters"

    def __init__(self) -> None:
        self._adapters: dict[str, AgentAdapter] | None = None

    def discover(self, *, refresh: bool = False) -> list[AgentAdapter]:
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
        adapters = {adapter.name: adapter for adapter in self.discover()}
        try:
            return adapters[name]
        except KeyError as exc:
            choices = ", ".join(adapters)
            raise KeyError(f"Unknown agent {name!r}; choose from: {choices}") from exc

    def select(self, names: list[str] | None) -> list[AgentAdapter]:
        return self.discover() if not names else [self.get(name) for name in names]


registry = AgentRegistry()
