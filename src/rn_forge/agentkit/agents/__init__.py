"""Adapter interfaces, discovery, and built-in agent implementations.

Use :class:`AgentAdapter` to implement an integration and :data:`registry` to discover
the Claude, Codex, and installed third-party adapters.
"""

from .base import AgentAdapter
from .registry import AgentRegistry, registry

__all__ = ["AgentAdapter", "AgentRegistry", "registry"]
