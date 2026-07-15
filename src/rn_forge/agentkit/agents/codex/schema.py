"""Managed Codex CLI configuration schema."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CodexConfig(BaseModel):
    """Common Codex settings with extra fields retained for compatibility."""

    model_config = ConfigDict(extra="allow")

    model: str | None = None
    approval_policy: (
        Literal["untrusted", "on-failure", "on-request", "never"] | None
    ) = None
    sandbox_mode: (
        Literal["read-only", "workspace-write", "danger-full-access"] | None
    ) = None
    model_reasoning_effort: (
        Literal["minimal", "low", "medium", "high", "xhigh"] | None
    ) = None
    web_search: Literal["disabled", "cached", "live"] | None = None
    features: dict[str, bool] = Field(default_factory=dict)
    mcp_servers: dict[str, Any] = Field(default_factory=dict)
