from rn_forge.agentkit.core.io import read_config, update_config, write_config


def test_round_trip_supported_formats(tmp_path) -> None:
    value = {"name": "agent", "nested": {"enabled": True}, "items": [1, 2]}
    for suffix in ("toml", "yaml", "json"):
        path = tmp_path / f"config.{suffix}"
        write_config(path, value)
        assert read_config(path) == value


def test_missing_optional_config_is_empty(tmp_path) -> None:
    assert read_config(tmp_path / "missing.toml", missing_ok=True) == {}


def test_update_preserves_toml_and_yaml_comments(tmp_path) -> None:
    toml = tmp_path / "commented.toml"
    toml.write_text("# heading\nvalue = 1 # keep this\n")
    update_config(toml, {"value": 2})
    assert "# heading" in toml.read_text()
    assert "# keep this" in toml.read_text()
    assert read_config(toml)["value"] == 2

    yaml = tmp_path / "commented.yaml"
    yaml.write_text("# heading\nvalue: 1 # keep this\n")
    update_config(yaml, {"value": 2})
    assert "# heading" in yaml.read_text()
    assert "# keep this" in yaml.read_text()
    assert read_config(yaml)["value"] == 2
