"""Managed-file declarations shared by agent adapters and the manager."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class Artifact:
    """One managed file an adapter renders or copies to a native path.

    Attributes:
        key: Stable identifier unique within an adapter scope.
        native_relative: Destination relative to the selected root.
        root: Agent discovery root or agentkit share root.
        template: Optional Jinja template name.
        source: Optional packaged static source file.
        executable: Whether writes enforce mode ``0o755``.

    Raises:
        ValueError: Both or neither content sources are set, or the native path
            is absolute.
    """

    key: str
    native_relative: Path
    root: Literal["agent", "share"] = "agent"
    template: str | None = None
    source: Path | None = None
    executable: bool = False

    def __post_init__(self) -> None:
        if (self.template is None) == (self.source is None):
            raise ValueError("Artifact requires exactly one of template or source")
        if self.native_relative.is_absolute():
            raise ValueError("Artifact native_relative must be relative")
