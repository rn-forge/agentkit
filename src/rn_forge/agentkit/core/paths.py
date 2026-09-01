"""Resolve rn-forge global and repository-local working-data paths.

The manager and adapters share these helpers so ``RNF_HOME`` overrides remain consistent
across managed sources, shared hooks, staging, state, and backups.
"""

from __future__ import annotations

import os
from pathlib import Path


def rnf_home() -> Path:
    """Return the rn-forge home, honoring the macsetup-compatible override."""
    return Path(os.environ.get("RNF_HOME", "~/.rn-forge")).expanduser()


def global_root() -> Path:
    """Return agentkit's global working-data root."""
    return rnf_home() / "share" / "agentkit"


def project_scope_root(repo_root: Path) -> Path:
    """Return agentkit's working-data root inside a repository.

    Args:
        repo_root: Repository containing local managed data.
    """
    return Path(repo_root) / ".rn-forge" / "agentkit"


def package_root() -> Path:
    """Return the installed ``rn_forge.agentkit`` package directory.

    Every packaged asset, template, and skill an adapter names as an artifact's source
    lives beneath this. It follows the *running* interpreter's import path, so it is a
    site-packages directory for a normal install and the repo ``src/`` tree for an
    editable one — which is exactly the distinction ``doctor`` reports when a target
    drifts from its source.
    """
    return Path(__file__).parents[1]
