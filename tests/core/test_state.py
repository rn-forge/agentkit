"""State is read back from disk, so it is untrusted input like any other file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.core.manager import apply_adapter
from rn_forge.agentkit.core.paths import global_root
from rn_forge.agentkit.core.state import StateStore


@pytest.mark.parametrize(
    "payload",
    [
        '{"/path/to/file": "not an object"}',
        '{"/path/to/file": 42}',
        '{"/path/to/file": ["a"]}',
        '{"/path/to/file": {"hash": 12345}}',
        # `record_many` always writes path/last_applied/source_layer, so a
        # hand-edited entry missing or mistyping one is corruption too, not
        # just a bad `hash`.
        '{"/path/to/file": {}}',
        '{"/path/to/file": {"path": "/path/to/file", "last_applied": "t", "source_layer": 1}}',
        '{"/path/to/file": {"path": "/path/to/file", "source_layer": "global"}}',
    ],
)
def test_malformed_entries_are_rejected_at_load(tmp_path: Path, payload: str) -> None:
    """A bad entry must fail loudly here, not as an AttributeError inside apply."""
    store = StateStore(tmp_path)
    store.path.write_text(payload)

    with pytest.raises(ValueError, match="Invalid state file"):
        store.load()


def test_apply_reports_malformed_state_as_a_domain_error(isolated_env) -> None:
    _, _, repo = isolated_env
    adapter = CodexAdapter()
    store = StateStore(global_root())
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('{"/somewhere": "bad"}')

    with pytest.raises(ValueError, match="Invalid state file"):
        apply_adapter(adapter, "global", repo)


def test_entry_missing_hash_is_still_valid(tmp_path: Path) -> None:
    """`hash` is the one field allowed to be absent; the other three are not."""
    store = StateStore(tmp_path)
    store.path.write_text(
        json.dumps(
            {
                "/path/to/file": {
                    "path": "/path/to/file",
                    "last_applied": "2026-01-01T00:00:00+00:00",
                    "source_layer": "global",
                }
            }
        )
    )

    loaded = store.load()

    assert loaded["/path/to/file"]["source_layer"] == "global"


def test_valid_state_round_trips(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    target = tmp_path / "artifact.toml"
    target.write_text("x = 1\n")

    store.record(target, "abc123", "global")
    entry = store.get(target)

    assert entry is not None
    assert entry["hash"] == "abc123"
    assert entry["source_layer"] == "global"


def test_record_many_writes_every_entry_in_one_cycle(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    first = tmp_path / "a.toml"
    second = tmp_path / "b.toml"
    for path in (first, second):
        path.write_text("x = 1\n")

    store.record_many([(first, "aaa", "global"), (second, "bbb", "packaged")])

    data = json.loads(store.path.read_text())
    assert len(data) == 2
    assert store.get(first) is not None
    assert store.get(second) is not None


def test_record_many_preserves_unrelated_existing_entries(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    existing = tmp_path / "kept.toml"
    added = tmp_path / "added.toml"
    for path in (existing, added):
        path.write_text("x = 1\n")
    store.record(existing, "keep", "global")

    store.record_many([(added, "new", "global")])

    kept = store.get(existing)
    assert kept is not None
    assert kept["hash"] == "keep"
