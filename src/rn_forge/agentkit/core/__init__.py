"""Core merge, render, file, state, path, and diagnostic services.

Adapters consume these services through :class:`ConfigMerger` and :class:`RenderEngine`;
CLI commands orchestrate them through ``core.manager``.
"""

from .config import ConfigMerger, MergeResult, parse_cli_overrides
from .render import RenderEngine

__all__ = ["ConfigMerger", "MergeResult", "RenderEngine", "parse_cli_overrides"]
