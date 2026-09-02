from pathlib import Path
from typing import Any

from pydantic import BaseModel

from rn_forge.agentkit.agents.base import AgentAdapter, Scope
from rn_forge.agentkit.core.artifacts import Artifact
from rn_forge.agentkit.core.manager import apply_adapter


class ExampleConfig(BaseModel):
    value: str = "default"


class ExampleAdapter(AgentAdapter):
    name = "example"

    def __init__(self, source: Path) -> None:
        self.source = source

    def schema(self) -> type[ExampleConfig]:
        return ExampleConfig

    def _artifacts(self) -> list[Artifact]:
        return [
            Artifact("config", Path(".example/config.txt"), template="config.j2"),
            Artifact(
                "hooks/guard.sh",
                Path("hooks/example/guard.sh"),
                root="share",
                source=self.source,
                executable=True,
            ),
        ]

    def _global_artifacts(self) -> list[Artifact]:
        return self._artifacts()

    def _local_artifacts(self) -> list[Artifact]:
        return self._artifacts()

    def render(self, merged_config: dict[str, Any], *, scope: Scope = "global") -> str:
        return f"value={merged_config['value']}\n"

    def parse_native(self, path: Path) -> dict[str, Any]:
        return {"value": path.read_text().removeprefix("value=").strip()}


def test_multi_artifact_apply_is_idempotent_executable_and_backed_up(
    isolated_env, tmp_path: Path
) -> None:
    _, _, repo = isolated_env
    source = tmp_path / "guard.sh"
    source.write_text("#!/bin/sh\nexit 0\n")
    adapter = ExampleAdapter(source)

    first = apply_adapter(adapter, "global", repo)
    second = apply_adapter(adapter, "global", repo)

    assert [result.artifact for result in first] == ["config", "hooks/guard.sh"]
    assert all(result.changed for result in first)
    assert not any(result.changed for result in second)
    assert first[1].native_path.stat().st_mode & 0o777 == 0o755

    first[0].native_path.write_text("manual config\n")
    config_reapplied = apply_adapter(adapter, "global", repo)
    assert config_reapplied[0].backup_path is not None

    first[1].native_path.write_text("manual hook\n")
    hook_reapplied = apply_adapter(adapter, "global", repo)
    assert hook_reapplied[1].backup_path is not None
