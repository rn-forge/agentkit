"""Apply, remove, capture, and init pipelines that act on adapter artifacts.

Each submodule owns one pipeline; this package re-exports the public verbs so call sites
import one module rather than reaching into a specific pipeline file.
"""

from __future__ import annotations

from .apply import apply_adapter, artifact_drifted, resolve_config, sync_adapter
from .capture import capture_adapter, capture_assets, capture_defaults
from .init import init_adapter, scaffold_managed_source
from .remove import remove_owned_artifacts, reset_adapter, strip_native_hooks
from .result import OperationResult

__all__ = [
    "OperationResult",
    "apply_adapter",
    "artifact_drifted",
    "capture_adapter",
    "capture_assets",
    "capture_defaults",
    "init_adapter",
    "remove_owned_artifacts",
    "reset_adapter",
    "resolve_config",
    "scaffold_managed_source",
    "strip_native_hooks",
    "sync_adapter",
]
