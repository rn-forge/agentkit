import json
import shutil
import subprocess
from pathlib import Path

import pytest

from rn_forge.agentkit.agents.claude import ClaudeAdapter
from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.core.manager import apply_adapter

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")

_WRAPPED = "# Title\n\nThis is a\nwrapped paragraph.\n"
_UNWRAPPED = "# Title\n\nThis is a wrapped paragraph.\n"


def _run(rnf: Path, agent: str, file_path: Path) -> subprocess.CompletedProcess:
    script = rnf / "share" / "agentkit" / agent / "hooks" / "post-write-unwrap-md.sh"
    payload = {"tool_input": {"file_path": str(file_path)}}
    return subprocess.run(
        [script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def test_unwrap_hook_rewraps_markdown_for_both_dialects(isolated_env) -> None:
    _, rnf, repo = isolated_env
    apply_adapter(ClaudeAdapter(), "global", repo)
    apply_adapter(CodexAdapter(), "global", repo)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    for agent in ("claude", "codex"):
        doc = repo / f"{agent}.md"
        doc.write_text(_WRAPPED)
        result = _run(rnf, agent, doc)
        assert result.returncode == 0
        assert doc.read_text() == _UNWRAPPED


def test_unwrap_hook_honors_nounwrap_marker(isolated_env) -> None:
    _, rnf, repo = isolated_env
    apply_adapter(ClaudeAdapter(), "global", repo)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".nounwrap").write_text("")

    doc = repo / "notes.md"
    doc.write_text(_WRAPPED)
    result = _run(rnf, "claude", doc)

    assert result.returncode == 0
    assert doc.read_text() == _WRAPPED


def test_unwrap_hook_ignores_non_markdown_files(isolated_env) -> None:
    _, rnf, repo = isolated_env
    apply_adapter(ClaudeAdapter(), "global", repo)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    doc = repo / "notes.txt"
    doc.write_text(_WRAPPED)
    result = _run(rnf, "claude", doc)

    assert result.returncode == 0
    assert doc.read_text() == _WRAPPED
