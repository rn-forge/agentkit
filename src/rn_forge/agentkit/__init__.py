"""Public package entry points for agentkit.

The package exposes its installed version and the :func:`main` console entry point;
command dispatch lives in :mod:`rn_forge.agentkit.cli`.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("rn-forge-agentkit")
except PackageNotFoundError:  # pragma: no cover - editable source without metadata
    # Never hard-code a number here: a stale literal misreports the running
    # version, which is worse than admitting the metadata is unavailable.
    __version__ = "unknown"


def main() -> None:
    """Run the agentkit command-line interface."""
    from .cli import app

    app()


__all__ = ["__version__", "main"]
