"""Persist applied hashes and snapshot native files before overwrites.

The manager records one state entry per native artifact and uses these hashes to
distinguish expected package updates from untracked manual drift.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .io import atomic_write


_backup_run_timestamp: str | None = None


def start_backup_run() -> None:
    """Start a new backup run, assigning its timestamp on first snapshot."""
    global _backup_run_timestamp
    _backup_run_timestamp = None


def _backup_timestamp() -> str:
    global _backup_run_timestamp
    if _backup_run_timestamp is None:
        _backup_run_timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    return _backup_run_timestamp


def content_hash(content: str | bytes) -> str:
    """Return a SHA-256 digest for text or byte content."""
    payload = content.encode() if isinstance(content, str) else content
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str | None:
    """Return a file's SHA-256 digest, or ``None`` when it is absent."""
    return content_hash(path.read_bytes()) if path.is_file() else None


def _resolved(native_path: Path) -> str:
    """Return the canonical string key a native path is recorded under."""
    return str(Path(native_path).expanduser().resolve())


class StateStore:
    """Persist native path hashes for one global or project scope.

    Args:
        scope_root: Working-data root containing ``state.json``.
    """

    def __init__(self, scope_root: Path) -> None:
        self.scope_root = Path(scope_root)
        self.path = self.scope_root / "state.json"

    def load(self) -> dict[str, dict[str, Any]]:
        """Load and validate state, returning an empty mapping when absent.

        Every entry is checked, not just the JSON root: a hand-edited or
        truncated state file that happens to parse would otherwise surface much
        later as an ``AttributeError`` deep inside apply. Each entry must carry
        the ``path``, ``last_applied``, and ``source_layer`` strings that
        ``record_many`` always writes; ``hash`` is the only field allowed to
        be absent.

        Raises:
            ValueError: The file is unreadable, is not an object, or holds an
                entry that is not a string-keyed object with those fields.
        """
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid state file {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Invalid state file {self.path}: expected an object")
        entries = cast(dict[Any, Any], data)
        validated: dict[str, dict[str, Any]] = {}
        for key, value in entries.items():
            if not isinstance(key, str):
                raise ValueError(
                    f"Invalid state file {self.path}: entry key {key!r} is not a string"
                )
            if not isinstance(value, dict):
                raise ValueError(
                    f"Invalid state file {self.path}: entry {key!r} is not an object"
                )
            entry = cast(dict[Any, Any], value)
            hash_value = entry.get("hash")
            if hash_value is not None and not isinstance(hash_value, str):
                raise ValueError(
                    f"Invalid state file {self.path}: entry {key!r} has a "
                    "non-string hash"
                )
            # `hash` is the only field genuinely optional at read time (a
            # freshly-removed entry can still be mid-write); `record_many`
            # always writes the rest, so a hand-edited file missing or
            # mistyping one is corruption, same as a bad hash.
            for field in ("path", "last_applied", "source_layer"):
                if field not in entry:
                    raise ValueError(
                        f"Invalid state file {self.path}: entry {key!r} is "
                        f"missing {field!r}"
                    )
                if not isinstance(entry[field], str):
                    raise ValueError(
                        f"Invalid state file {self.path}: entry {key!r} has a "
                        f"non-string {field!r}"
                    )
            validated[key] = cast(dict[str, Any], entry)
        return validated

    def get(self, native_path: Path) -> dict[str, Any] | None:
        """Return the state entry for a resolved native path."""
        return self.load().get(_resolved(native_path))

    def record(self, native_path: Path, digest: str, source_layer: str) -> None:
        """Atomically record one artifact digest and source layer."""
        self.record_many([(native_path, digest, source_layer)])

    def record_many(self, entries: Iterable[tuple[Path, str, str]]) -> None:
        """Record several artifacts in one read-modify-write cycle.

        One write per operation rather than per artifact keeps the window in which a
        concurrent invocation can clobber entries as small as the file lock allows, and
        leaves state consistent if the process dies mid-apply.
        """
        with self._locked():
            data = self.load()
            stamp = datetime.now(UTC).isoformat()
            for native_path, digest, source_layer in entries:
                resolved = _resolved(native_path)
                data[resolved] = {
                    "path": resolved,
                    "hash": digest,
                    "last_applied": stamp,
                    "source_layer": source_layer,
                }
            self._write(data)

    def remove(self, native_path: Path) -> None:
        """Remove a native path's state entry."""
        with self._locked():
            data = self.load()
            data.pop(_resolved(native_path), None)
            self._write(data)

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        atomic_write(self.path, json.dumps(data, indent=2, sort_keys=True) + "\n")

    @contextmanager
    def _locked(self) -> Generator[None]:
        """Serialize read-modify-write cycles against other agentkit processes.

        Two invocations updating the same scope would otherwise each load, edit,
        and write the whole file, losing the other's entries. The lock is
        advisory and best effort: on a filesystem without ``flock`` support the
        update proceeds unserialized rather than failing the command.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(".lock")
        try:
            handle = lock_path.open("w")
        except OSError:
            yield
            return
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except OSError:
                pass
            yield
        finally:
            handle.close()

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
    timestamp = _backup_timestamp()
    try:
        relative = path.expanduser().resolve().relative_to(Path.home().resolve())
    except ValueError:
        relative = Path(*path.expanduser().resolve().parts[1:])
    destination = Path(scope_root) / "backups" / timestamp / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return destination
