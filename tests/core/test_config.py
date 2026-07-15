from pydantic import BaseModel, Field

from rn_forge.agentkit.core.config import ConfigMerger, parse_cli_overrides


class MergeSchema(BaseModel):
    replace: list[int] = []
    append: list[int] = Field(
        default_factory=list, json_schema_extra={"merge_strategy": "append"}
    )


def test_deep_merge_list_strategies_and_provenance() -> None:
    result = ConfigMerger(MergeSchema).merge(
        ("defaults", {"nested": {"one": 1, "two": 2}, "replace": [1], "append": [1]}),
        ("global", {"nested": {"two": 20}, "replace": [2], "append": [2]}),
        ("local", {"nested": {"three": 3}}),
    )

    assert result.config == {
        "nested": {"one": 1, "two": 20, "three": 3},
        "replace": [2],
        "append": [1, 2],
    }
    assert result.provenance["nested.one"] == "defaults"
    assert result.provenance["nested.two"] == "global"
    assert result.provenance["nested.three"] == "local"
    merged, provenance = result
    assert merged is result.config
    assert provenance is result.provenance


def test_parse_cli_overrides_supports_dotted_typed_values() -> None:
    assert parse_cli_overrides(
        ["model=gpt-5", "features.fast=true", "count=3", 'items=["a", "b"]']
    ) == {
        "model": "gpt-5",
        "features": {"fast": True},
        "count": 3,
        "items": ["a", "b"],
    }
