"""Format-aware configuration and atomic file I/O."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

import tomlkit
from ruamel.yaml import YAML


class ConfigIOError(ValueError):
    """Raised when a configuration file cannot be read or encoded."""


def _suffix(path: Path, format_name: str | None = None) -> str:
    suffix = (format_name or path.suffix.lstrip(".")).lower()
    aliases = {"yml": "yaml"}
    return aliases.get(suffix, suffix)


def loads_config(text: str, format_name: str) -> dict[str, Any]:
    """Parse TOML, YAML, or JSON text into a plain dictionary."""
    try:
        match _suffix(Path("config." + format_name)):
            case "toml":
                value = tomlkit.loads(text).unwrap()
            case "yaml":
                yaml = YAML(typ="rt")
                value = yaml.load(text) or {}
            case "json":
                value = json.loads(text)
            case other:
                raise ConfigIOError(f"Unsupported config format: {other}")
    except ConfigIOError:
        raise
    except Exception as exc:
        raise ConfigIOError(
            f"Invalid {format_name.upper()} configuration: {exc}"
        ) from exc
    if not isinstance(value, Mapping):
        raise ConfigIOError("Configuration root must be a mapping")
    return _to_plain(value)


def dumps_config(data: Mapping[str, Any], format_name: str) -> str:
    """Serialize a mapping in a stable, human-readable form."""
    plain = _to_plain(data)
    match _suffix(Path("config." + format_name)):
        case "toml":
            return tomlkit.dumps(plain)
        case "yaml":
            from io import StringIO

            stream = StringIO()
            yaml = YAML(typ="rt")
            yaml.default_flow_style = False
            yaml.dump(plain, stream)
            return stream.getvalue()
        case "json":
            return json.dumps(plain, indent=2, sort_keys=True) + "\n"
        case other:
            raise ConfigIOError(f"Unsupported config format: {other}")


def read_config(path: Path, *, missing_ok: bool = False) -> dict[str, Any]:
    """Read a configuration file, optionally treating a missing file as empty."""
    path = Path(path)
    if not path.exists():
        if missing_ok:
            return {}
        raise ConfigIOError(f"Configuration file does not exist: {path}")
    return loads_config(path.read_text(encoding="utf-8"), _suffix(path))


def read_config_document(path: Path) -> Any:
    """Read a round-trip document, retaining TOML/YAML comments and style."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        match _suffix(path):
            case "toml":
                return tomlkit.loads(text)
            case "yaml":
                return YAML(typ="rt").load(text) or {}
            case "json":
                return json.loads(text)
            case other:
                raise ConfigIOError(f"Unsupported config format: {other}")
    except ConfigIOError:
        raise
    except Exception as exc:
        raise ConfigIOError(f"Invalid configuration {path}: {exc}") from exc


def write_config_document(path: Path, document: Any) -> None:
    """Atomically write a round-trip document without flattening its metadata."""
    path = Path(path)
    match _suffix(path):
        case "toml":
            content = tomlkit.dumps(document)
        case "yaml":
            from io import StringIO

            stream = StringIO()
            yaml = YAML(typ="rt")
            yaml.dump(document, stream)
            content = stream.getvalue()
        case "json":
            content = json.dumps(document, indent=2, sort_keys=True) + "\n"
        case other:
            raise ConfigIOError(f"Unsupported config format: {other}")
    atomic_write(path, content)


def update_config(path: Path, updates: Mapping[str, Any]) -> None:
    """Deep-update a config while preserving existing TOML/YAML comments."""
    path = Path(path)
    if not path.exists():
        write_config(path, updates)
        return
    document = read_config_document(path)
    if not isinstance(document, MutableMapping):
        raise ConfigIOError("Configuration root must be a mutable mapping")
    _deep_update_document(document, updates)
    write_config_document(path, document)


def write_config(path: Path, data: Mapping[str, Any]) -> None:
    """Atomically write structured configuration based on the file suffix."""
    atomic_write(path, dumps_config(data, _suffix(path)))


def atomic_write(path: Path, content: str | bytes) -> None:
    """Replace a file atomically while retaining sensible permissions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    kwargs: dict[str, Any] = {} if isinstance(content, bytes) else {"encoding": "utf-8"}
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, mode, **kwargs) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _to_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(item) for item in value]
    return value


def _deep_update_document(
    target: MutableMapping[str, Any], updates: Mapping[str, Any]
) -> None:
    for key, value in updates.items():
        current = target.get(key)
        if isinstance(current, MutableMapping) and isinstance(value, Mapping):
            _deep_update_document(current, value)
        else:
            target[key] = value
