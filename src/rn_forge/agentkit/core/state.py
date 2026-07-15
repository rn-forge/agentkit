"""Persist applied hashes and snapshot native files before overwrites.

The manager records one state entry per native artifact and uses these hashes
to distinguish expected package updates from untracked manual drift.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .io import atomic_write


def content_hash(content: str | bytes) -> str:
    """Return a SHA-256 digest for text or byte content."""
    payload = content.encode() if isinstance(content, str) else content
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str | None:
    """Return a file's SHA-256 digest, or ``None`` when it is absent."""
    return content_hash(path.read_bytes()) if path.is_file() else None


class StateStore:
    """Persist native path hashes for one global or project scope.

    Args:
        scope_root: Working-data root containing ``state.json``.
    """

    def __init__(self, scope_root: Path) -> None:
        self.scope_root = Path(scope_root)
        self.path = self.scope_root / "state.json"

    def load(self) -> dict[str, dict[str, Any]]:
        """Load state, returning an empty mapping when no state exists."""
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid state file {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Invalid state file {self.path}: expected an object")
        return cast(dict[str, dict[str, Any]], data)

    def get(self, native_path: Path) -> dict[str, Any] | None:
        """Return the state entry for a resolved native path."""
        return self.load().get(str(Path(native_path).expanduser().resolve()))

    def record(self, native_path: Path, digest: str, source_layer: str) -> None:
        """Atomically record an artifact digest and source layer."""
        data = self.load()
        resolved = str(Path(native_path).expanduser().resolve())
        data[resolved] = {
            "path": resolved,
            "hash": digest,
            "last_applied": datetime.now(UTC).isoformat(),
            "source_layer": source_layer,
        }
        atomic_write(self.path, json.dumps(data, indent=2, sort_keys=True) + "\n")

    def remove(self, native_path: Path) -> None:
        """Remove a native path's state entry."""
        data = self.load()
        data.pop(str(Path(native_path).expanduser().resolve()), None)
        atomic_write(self.path, json.dumps(data, indent=2, sort_keys=True) + "\n")

    def stale_entries(self) -> list[str]:
        """Return recorded native paths that no longer exist."""
        return [key for key in self.load() if not Path(key).exists()]


def backup_file(path: Path, scope_root: Path) -> Path | None:
    """Snapshot a file under ``backups/<UTC timestamp>/``.

    Returns:
        The backup path, or ``None`` when the source is not a file.
    """
    path = Path(path)
    if not path.is_file():
        return None
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    try:
        relative = path.expanduser().resolve().relative_to(Path.home().resolve())
    except ValueError:
        relative = Path(*path.expanduser().resolve().parts[1:])
    destination = Path(scope_root) / "backups" / timestamp / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return destination
