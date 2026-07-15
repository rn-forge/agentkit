"""Applied-state hashes and backup management."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import atomic_write


def content_hash(content: str | bytes) -> str:
    payload = content.encode() if isinstance(content, str) else content
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str | None:
    return content_hash(path.read_bytes()) if path.is_file() else None


class StateStore:
    """Persist native path hashes for one global or project scope."""

    def __init__(self, scope_root: Path) -> None:
        self.scope_root = Path(scope_root)
        self.path = self.scope_root / "state.json"

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid state file {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Invalid state file {self.path}: expected an object")
        return data

    def get(self, native_path: Path) -> dict[str, Any] | None:
        return self.load().get(str(Path(native_path).expanduser().resolve()))

    def record(self, native_path: Path, digest: str, source_layer: str) -> None:
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
        data = self.load()
        data.pop(str(Path(native_path).expanduser().resolve()), None)
        atomic_write(self.path, json.dumps(data, indent=2, sort_keys=True) + "\n")

    def stale_entries(self) -> list[str]:
        return [key for key in self.load() if not Path(key).exists()]


def backup_file(path: Path, scope_root: Path) -> Path | None:
    """Snapshot a file under ``backups/<UTC timestamp>/``."""
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
