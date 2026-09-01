"""Managed-file declarations shared by agent adapters and the manager."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ArtifactKind = Literal["config", "hook", "skill", "doc"]
"""What an artifact *is*, reported by ``doctor`` as the row's type.

``config`` covers a native configuration file (including a hook manifest an agent reads
as config); ``hook`` an executable hook script or its helper; ``skill`` a packaged skill
file; ``doc`` a human-facing instruction document.
"""

@dataclass(frozen=True, slots=True)
class Artifact:
    """One managed file an adapter renders or copies to a native path.

    Attributes:
        key: Stable identifier unique within an adapter scope.
        kind: What the file is, used to group diagnostic output.
        native_relative: Destination relative to the selected root.
        root: Agent discovery root or agentkit share root.
        template: Optional Jinja template name.
        source: Optional packaged static source file.
        executable: Whether writes enforce mode ``0o755``.
        seed_only: Write only when the native path is absent, then leave the
            file to the repository. For hand-authored files agentkit scaffolds
            but does not own.

    Raises:
        ValueError: Both or neither content sources are set, or the native path
            is absolute, escapes its root, or is empty.
    """

    key: str
    native_relative: Path
    kind: ArtifactKind = "config"
    root: Literal["agent", "share"] = "agent"
    template: str | None = None
    source: Path | None = None
    executable: bool = False
    seed_only: bool = False

    def __post_init__(self) -> None:
        if (self.template is None) == (self.source is None):
            raise ValueError("Artifact requires exactly one of template or source")
        if not self.key.strip():
            raise ValueError("Artifact key must be a non-empty identifier")
        if self.native_relative.is_absolute():
            raise ValueError("Artifact native_relative must be relative")
        # A relative path is not automatically an in-root path: a third-party
        # adapter declaring `../../.ssh/config` would otherwise write outside
        # the agent or share root the destination is resolved against.
        parts = self.native_relative.parts
        if not parts:
            raise ValueError("Artifact native_relative must not be empty")
        if ".." in parts:
            raise ValueError(
                f"Artifact native_relative must not traverse upwards: "
                f"{self.native_relative}"
            )
