from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    """Isolate native and managed agent paths beneath pytest's temp directory."""
    home = tmp_path / "home"
    rnf = tmp_path / "rnf"
    repo = tmp_path / "repo"
    home.mkdir()
    rnf.mkdir()
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("RNF_HOME", str(rnf))
    return home, rnf, repo
