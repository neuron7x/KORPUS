from __future__ import annotations

from korpus.application.capability_gateway.effect_safety import _compensation_cycle_errors


def test_compensation_cycle_detection_is_not_bounded_by_python_recursion_depth() -> None:
    version = "1.0.0"
    edges = {
        (f"reference.scale.node{i:04d}", version):
        (f"reference.scale.node{i + 1:04d}", version)
        for i in range(2_000)
    }

    assert _compensation_cycle_errors(edges) == ()


def test_large_cycle_is_detected_without_recursive_traversal() -> None:
    version = "1.0.0"
    edges = {
        (f"reference.scale.node{i:04d}", version):
        (f"reference.scale.node{i + 1:04d}", version)
        for i in range(1_500)
    }
    edges[("reference.scale.node1500", version)] = ("reference.scale.node0750", version)

    errors = _compensation_cycle_errors(edges)

    assert len(errors) == 1
    assert errors[0].startswith("compensation cycle detected: reference.scale.node0750@1.0.0")
    assert errors[0].endswith("reference.scale.node0750@1.0.0")
