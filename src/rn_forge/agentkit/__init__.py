"""Unified configuration management for AI coding agents."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("rn-forge-agentkit")
except PackageNotFoundError:  # pragma: no cover - editable source without metadata
    __version__ = "0.1.0"


def main() -> None:
    """Run the agentkit command-line interface."""
    from .cli import app

    app()


__all__ = ["__version__", "main"]
