import pytest

from rn_forge.agentkit.core.render import RenderEngine, RenderError


def test_render_string_is_strict() -> None:
    engine = RenderEngine()
    assert engine.render_string("hello {{ name }}", {"name": "agent"}) == "hello agent"
    with pytest.raises(RenderError):
        engine.render_string("{{ missing }}", {})
