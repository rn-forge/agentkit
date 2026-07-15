"""Provide structural layer changes and rendered-versus-native text diffs.

The shared ``diff`` command uses these helpers after configuration resolution.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class KeyChange:
    """One flattened configuration value introduced by a layer."""

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
    """Return a conventional unified diff, or an empty string when equal."""
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
    """Describe the flattened keys changed by each precedence layer."""
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
    """Flatten nested mappings into dotted paths for structural comparison."""
    result: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            result.update(flatten(cast(Mapping[str, Any], item), path))
        else:
            result[path] = item
    return result
