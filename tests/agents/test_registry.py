"""Third-party adapters are untrusted input; discovery must contain them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from importlib import import_module

# `agents/__init__.py` re-exports the singleton as `registry`, shadowing the
# submodule of the same name, so resolve the module explicitly.
registry_module = import_module("rn_forge.agentkit.agents.registry")
from rn_forge.agentkit.agents.base import AgentAdapter
from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.agents.registry import AgentRegistry
from rn_forge.agentkit.core.artifacts import Artifact


@dataclass
class _FakeEntryPoint:
    """Stand-in for importlib.metadata.EntryPoint with a scripted load()."""

    name: str
    value: str
    result: Any = None
    error: Exception | None = None

    def load(self) -> Any:
        if self.error is not None:
            raise self.error
        return self.result


def _registry_with(monkeypatch: pytest.MonkeyPatch, *points: _FakeEntryPoint):
    monkeypatch.setattr(registry_module, "entry_points", lambda group: list(points))
    return AgentRegistry()


def _names(registry: AgentRegistry) -> list[str]:
    return [adapter.name for adapter in registry.discover()]


def test_a_broken_plugin_does_not_break_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry_with(
        monkeypatch,
        _FakeEntryPoint("broken", "broken:Adapter", error=ImportError("no module")),
    )

    assert _names(registry) == ["claude", "codex"]
    assert [error.entry_point for error in registry.errors] == ["broken"]
    assert "ImportError" in registry.errors[0].reason


def test_a_plugin_constructor_failure_is_contained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode() -> AgentAdapter:
        raise RuntimeError("bad config")

    registry = _registry_with(
        monkeypatch, _FakeEntryPoint("boom", "boom:make", result=explode)
    )

    assert _names(registry) == ["claude", "codex"]
    assert "RuntimeError: bad config" in registry.errors[0].reason


def test_a_non_adapter_entry_point_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry_with(
        monkeypatch, _FakeEntryPoint("wrong", "wrong:thing", result=lambda: object())
    )

    assert _names(registry) == ["claude", "codex"]
    assert "not an AgentAdapter" in registry.errors[0].reason


def test_a_plugin_cannot_replace_a_built_in_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silently shadowing `codex` would redirect every write agentkit makes."""

    class Impostor(CodexAdapter):
        @property
        def name(self) -> str:
            return "codex"

    registry = _registry_with(
        monkeypatch, _FakeEntryPoint("evil", "evil:Impostor", result=Impostor)
    )

    assert _names(registry) == ["claude", "codex"]
    assert not isinstance(registry.get("codex"), Impostor)
    assert "reserved by a built-in adapter" in registry.errors[0].reason


def test_an_unsafe_adapter_name_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapter names become directory names beneath the agentkit roots."""

    class Traversing(CodexAdapter):
        @property
        def name(self) -> str:
            return "../../escape"

    registry = _registry_with(
        monkeypatch, _FakeEntryPoint("bad-name", "bad:Traversing", result=Traversing)
    )

    assert _names(registry) == ["claude", "codex"]
    assert "must match" in registry.errors[0].reason


def test_discovery_order_is_independent_of_entry_point_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _registry_with(
        monkeypatch,
        _FakeEntryPoint("z", "z:x", error=ImportError("z")),
        _FakeEntryPoint("a", "a:x", error=ImportError("a")),
    )
    second = _registry_with(
        monkeypatch,
        _FakeEntryPoint("a", "a:x", error=ImportError("a")),
        _FakeEntryPoint("z", "z:x", error=ImportError("z")),
    )

    assert _names(first) == _names(second)
    assert [error.entry_point for error in first.errors] == ["a", "z"]
    assert [error.entry_point for error in second.errors] == ["a", "z"]


def test_duplicate_artifact_keys_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two artifacts sharing a key make the state record ambiguous."""

    class Colliding(CodexAdapter):
        @property
        def name(self) -> str:
            return "colliding"

        def artifacts(self, scope: Any) -> list[Artifact]:
            return [
                Artifact("config", Path("a.toml"), template="codex/config.toml.j2"),
                Artifact("config", Path("b.toml"), template="codex/config.toml.j2"),
            ]

    registry = _registry_with(
        monkeypatch, _FakeEntryPoint("dupe", "dupe:Colliding", result=Colliding)
    )

    assert _names(registry) == ["claude", "codex"]
    assert "duplicate artifact keys" in registry.errors[0].reason


def test_missing_primary_config_artifact_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scope with no `config` key would break `primary_artifact()` later.

    Checking this at discovery means a plugin missing (or duplicating) its primary
    config artifact is rejected up front instead of failing the first time some later
    command calls `primary_artifact()`.
    """

    class Configless(CodexAdapter):
        @property
        def name(self) -> str:
            return "configless"

        def artifacts(self, scope: Any) -> list[Artifact]:
            return [Artifact("AGENTS.md", Path("AGENTS.md"), template="x.j2")]

    registry = _registry_with(
        monkeypatch,
        _FakeEntryPoint("no-config", "no-config:Configless", result=Configless),
    )

    assert _names(registry) == ["claude", "codex"]
    assert "exactly one 'config' artifact" in registry.errors[0].reason


def test_artifacts_reject_upward_traversal() -> None:
    with pytest.raises(ValueError, match="traverse upwards"):
        Artifact("escape", Path("../../.ssh/config"), template="x.j2")


def test_artifacts_reject_absolute_paths() -> None:
    with pytest.raises(ValueError, match="must be relative"):
        Artifact("escape", Path("/etc/passwd"), template="x.j2")
