"""Share the operation-result type and write-diffing helpers across pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...agents.base import AgentAdapter, Scope
from ..artifacts import Artifact
from ..diff import unified_diff
from ..state import content_hash, file_hash


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Outcome of one action on one managed artifact."""

    agent: str
    artifact: str
    action: str
    changed: bool
    native_path: Path
    rendered_path: Path
    diff: str = ""
    backup_path: Path | None = None
    message: str = ""


def managed_copy_path(
    adapter: AgentAdapter,
    root: Path,
    scope: Scope,
    artifact: Artifact,
    native: Path,
) -> Path:
    if artifact.root == "share":
        return native
    return adapter.rendered_path(root, scope, artifact)


def content_diff(content: str | bytes, native: Path, rendered: Path) -> str:
    if file_hash(native) == content_hash(content):
        return ""
    if isinstance(content, bytes):
        try:
            expected = content.decode("utf-8")
        except UnicodeDecodeError:
            return f"binary artifact differs: {native}\n"
    else:
        expected = content
    try:
        actual = native.read_text(encoding="utf-8") if native.is_file() else ""
    except UnicodeDecodeError:
        return f"binary artifact differs: {native}\n"
    return unified_diff(
        expected,
        actual,
        expected_name=str(rendered),
        actual_name=str(native),
    )


def seeded_result(
    adapter: AgentAdapter,
    artifact: Artifact,
    action: str,
    native: Path,
    rendered: Path,
) -> OperationResult:
    """Report a seed-only artifact that already exists as left untouched."""
    return OperationResult(
        adapter.name,
        artifact.key,
        action,
        False,
        native,
        rendered,
        message="exists; owned by the repository",
    )


def mode_differs(path: Path, artifact: Artifact) -> bool:
    return (
        artifact.executable and path.is_file() and path.stat().st_mode & 0o777 != 0o755
    )


def highest_source(provenance: dict[str, str]) -> str:
    priority = {"defaults": 0, "global": 1, "local": 2, "overrides": 3}
    return max(
        provenance.values(), key=lambda name: priority.get(name, -1), default="defaults"
    )
