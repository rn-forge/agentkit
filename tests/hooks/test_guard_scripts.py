import json
import shutil
import subprocess

import pytest

from rn_forge.agentkit.agents.claude import ClaudeAdapter
from rn_forge.agentkit.agents.codex import CodexAdapter
from rn_forge.agentkit.core.manager import apply_adapter

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")


def test_bash_guard_dialects_and_union_patterns(isolated_env) -> None:
    _, rnf, repo = isolated_env
    apply_adapter(ClaudeAdapter(), "global", repo)
    apply_adapter(CodexAdapter(), "global", repo)

    for command in ("rm -rf /", 'rm -rf "$HOME"', "psql -c 'TRUNCATE;'"):
        payload = {"tool_input": {"command": command}}
        claude = _run(rnf, "claude", "pre-bash-guard.sh", payload)
        codex = _run(rnf, "codex", "pre-bash-guard.sh", payload)
        assert claude.returncode == 2
        assert "BLOCKED [pre-bash-guard]" in claude.stderr
        assert codex.returncode == 0
        assert json.loads(codex.stdout)["decision"] == "block"

    benign = {"tool_input": {"command": "printf hello"}}
    for agent in ("claude", "codex"):
        result = _run(rnf, agent, "pre-bash-guard.sh", benign)
        assert result.returncode == 0
        assert not result.stdout
        assert not result.stderr


@pytest.mark.parametrize(
    "token",
    [
        "sk-abcdefghijklmnop1234",
        "ghp_abcdefghijklmnopqrstuvwxyz",
        "xoxb-abcdefghijklmnop",
    ],
)
def test_prompt_secret_guard_dialects_and_union_patterns(
    isolated_env, token: str
) -> None:
    _, rnf, repo = isolated_env
    apply_adapter(ClaudeAdapter(), "global", repo)
    apply_adapter(CodexAdapter(), "global", repo)
    payload = {"prompt": f"please use {token}"}

    claude = _run(rnf, "claude", "user-prompt-secret-guard.sh", payload)
    codex = _run(rnf, "codex", "user-prompt-secret-guard.sh", payload)

    assert claude.returncode == 2
    assert "BLOCKED [user-prompt-secret-guard]" in claude.stderr
    assert codex.returncode == 0
    assert json.loads(codex.stdout)["decision"] == "block"


def _run(rnf, agent: str, script: str, payload: dict) -> subprocess.CompletedProcess:
    path = rnf / "share" / "agentkit" / "hooks" / agent / script
    return subprocess.run(
        [path], input=json.dumps(payload), text=True, capture_output=True, check=False
    )
