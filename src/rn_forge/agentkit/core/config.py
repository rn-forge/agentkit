"""Layered configuration merging with per-key provenance."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import tomlkit
from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Merged config and a dotted-key to source-layer provenance map."""

    config: dict[str, Any]
    provenance: dict[str, str]

    def __iter__(self):
        yield self.config
        yield self.provenance


class ConfigMerger:
    """Deep-merge configuration layers in increasing precedence order."""

    def __init__(
        self,
        schema: type[BaseModel] | None = None,
        *,
        append_paths: Iterable[str] = (),
    ) -> None:
        inferred = _append_paths_from_schema(schema) if schema else set()
        self.append_paths = inferred | set(append_paths)

    def merge(
        self,
        *layers: Mapping[str, Any] | tuple[str, Mapping[str, Any]],
        layer_names: Sequence[str] | None = None,
    ) -> MergeResult:
        """Merge mappings or ``(name, mapping)`` pairs.

        Unnamed layers use the conventional names defaults, global, local,
        overrides, then layer-N. Dictionaries merge recursively; lists replace
        unless their dotted field path is marked with ``merge_strategy=append``.
        """
        conventional = ("defaults", "global", "local", "overrides")
        named: list[tuple[str, Mapping[str, Any]]] = []
        for index, layer in enumerate(layers):
            if (
                isinstance(layer, tuple)
                and len(layer) == 2
                and isinstance(layer[0], str)
                and isinstance(layer[1], Mapping)
            ):
                named.append((layer[0], layer[1]))
            else:
                mapping = cast(Mapping[str, Any], layer)
                name = (
                    layer_names[index]
                    if layer_names and index < len(layer_names)
                    else conventional[index]
                    if index < len(conventional)
                    else f"layer-{index + 1}"
                )
                named.append((name, mapping))

        merged: dict[str, Any] = {}
        provenance: dict[str, str] = {}
        for name, layer in named:
            _deep_merge(merged, layer, name, provenance, self.append_paths)
        return MergeResult(merged, provenance)


def defaults_for(schema: type[BaseModel]) -> dict[str, Any]:
    """Return fully materialized schema defaults."""
    return schema().model_dump(mode="python", exclude_none=True)


def parse_cli_overrides(values: Iterable[str]) -> dict[str, Any]:
    """Turn repeated ``--set dotted.key=value`` expressions into a mapping."""
    result: dict[str, Any] = {}
    for expression in values:
        if "=" not in expression:
            raise ValueError(f"Override must be KEY=VALUE: {expression!r}")
        key, raw = expression.split("=", 1)
        parts = [part for part in key.strip().split(".") if part]
        if not parts:
            raise ValueError(f"Override key cannot be empty: {expression!r}")
        cursor = result
        for part in parts[:-1]:
            existing = cursor.setdefault(part, {})
            if not isinstance(existing, dict):
                raise ValueError(f"Override collides with scalar key: {key!r}")
            cursor = existing
        cursor[parts[-1]] = _parse_scalar(raw)
    return result


def _parse_scalar(raw: str) -> Any:
    stripped = raw.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        try:
            return tomlkit.loads(f"value = {stripped}\n")["value"].unwrap()
        except Exception:
            return raw


def _deep_merge(
    target: dict[str, Any],
    incoming: Mapping[str, Any],
    layer: str,
    provenance: dict[str, str],
    append_paths: set[str],
    prefix: str = "",
) -> None:
    for key, value in incoming.items():
        key = str(key)
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value, layer, provenance, append_paths, path)
            provenance[path] = layer
        elif isinstance(value, Mapping):
            target[key] = {}
            _deep_merge(target[key], value, layer, provenance, append_paths, path)
            provenance[path] = layer
        elif (
            path in append_paths
            and isinstance(value, list)
            and isinstance(target.get(key), list)
        ):
            target[key] = copy.deepcopy(target[key]) + copy.deepcopy(value)
            provenance[path] = layer
        else:
            target[key] = copy.deepcopy(value)
            _mark_provenance(value, path, layer, provenance)


def _mark_provenance(
    value: Any, path: str, layer: str, provenance: dict[str, str]
) -> None:
    provenance[path] = layer
    if isinstance(value, Mapping):
        for key, child in value.items():
            _mark_provenance(child, f"{path}.{key}", layer, provenance)


def _append_paths_from_schema(schema: type[BaseModel], prefix: str = "") -> set[str]:
    result: set[str] = set()
    for name, field in schema.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        extra = field.json_schema_extra
        if isinstance(extra, dict) and extra.get("merge_strategy") == "append":
            result.add(path)
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            result.update(_append_paths_from_schema(annotation, path))
    return result
