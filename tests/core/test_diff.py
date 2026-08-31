from rn_forge.agentkit.core.diff import layered_changes, unified_diff


def test_unified_diff_and_layered_changes() -> None:
    assert unified_diff("same\n", "same\n") == ""
    difference = unified_diff("new\n", "old\n")
    assert "-old" in difference
    assert "+new" in difference

    changes = layered_changes([("defaults", {"a": 1}), ("global", {"a": 2})])
    assert [(item.path, item.layer, item.before, item.after) for item in changes] == [
        ("a", "defaults", None, 1),
        ("a", "global", 1, 2),
    ]
