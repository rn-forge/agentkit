"""Managed Claude Code settings schema."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PermissionsConfig(BaseModel):
    """Claude permission lists with append-on-merge behavior."""

    model_config = ConfigDict(extra="allow")

    allow: list[str] = Field(
        default_factory=list, json_schema_extra={"merge_strategy": "append"}
    )
    deny: list[str] = Field(
        default_factory=list, json_schema_extra={"merge_strategy": "append"}
    )
    ask: list[str] = Field(
        default_factory=list, json_schema_extra={"merge_strategy": "append"}
    )
    defaultMode: str | None = None


class ClaudeConfig(BaseModel):
    """Useful Claude defaults while permitting forward-compatible settings."""

    model_config = ConfigDict(extra="allow")

    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    env: dict[str, str] = Field(default_factory=dict)
    hooks: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    includeCoAuthoredBy: bool | None = None
    effortLevel: str | None = None
    outputStyle: str | None = None
    extraKnownMarketplaces: dict[str, Any] = Field(default_factory=dict)
