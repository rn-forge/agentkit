from pathlib import Path

from rn_forge.agentkit.core.paths import global_root, project_scope_root, rnf_home


def test_rnf_home_override_and_scope_roots(isolated_env) -> None:
    _, rnf, repo = isolated_env

    assert rnf_home() == rnf
    assert global_root() == rnf / "share" / "agentkit"
    assert project_scope_root(repo) == repo / ".rn-forge" / "agentkit"


def test_rnf_home_defaults_beneath_home(isolated_env, monkeypatch) -> None:
    home, _, _ = isolated_env
    monkeypatch.delenv("RNF_HOME")

    assert rnf_home() == Path(home) / ".rn-forge"
