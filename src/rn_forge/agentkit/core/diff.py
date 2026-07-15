"""Structural and rendered/native configuration diffing."""

from __future__ import annotations

import difflib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class KeyChange:
    path: str
    layer: str
    before: Any
    after: Any


def unified_diff(
    expected: str,
    actual: str,
    *,
    expected_name: str = "rendered",
    actual_name: str = "native",
) -> str:
    """Return a conventional unified diff (empty when contents match)."""
    return "".join(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=actual_name,
            tofile=expected_name,
        )
    )


def layered_changes(
    layers: Sequence[tuple[str, Mapping[str, Any]]],
) -> list[KeyChange]:
    """Describe which flattened keys each layer changes."""
    current: dict[str, Any] = {}
    changes: list[KeyChange] = []
    for name, layer in layers:
        flattened = flatten(layer)
        for path, after in flattened.items():
            before = current.get(path)
            if before != after:
                changes.append(KeyChange(path, name, before, after))
            current[path] = after
    return changes


def flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            result.update(flatten(item, path))
        else:
            result[path] = item
    return result
