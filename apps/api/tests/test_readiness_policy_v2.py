from __future__ import annotations

import json
from pathlib import Path

from korpus.application.assurance_calculus import DimensionPolicy, ReadinessPolicy

ROOT = Path(__file__).resolve().parents[3]
MODEL = ROOT / "config/assurance/readiness-model.v2.json"
CLASSES = ROOT / "config/assurance/evidence-classes.v1.json"
DAG = ROOT / "config/assurance/gate-dependency-dag.v1.json"


def test_readiness_v2_weights_form_a_normalized_policy() -> None:
    payload = json.loads(MODEL.read_text(encoding="utf-8"))
    weights = payload["weights"]
    policy = ReadinessPolicy(
        tuple(DimensionPolicy(name, float(weight)) for name, weight in weights.items()),
        (),
    )
    assert len(policy.dimensions) == 8
    assert abs(sum(item.weight for item in policy.dimensions) - 1.0) < 1e-12
    assert payload["kind"] == "normative_engineering_policy_not_probability_model"
    assert payload["minimum_engineering_release_candidate"] == 92.0
    assert payload["target_engineering_release_candidate"] == 94.0


def test_evidence_class_registry_is_strictly_ordered() -> None:
    payload = json.loads(CLASSES.read_text(encoding="utf-8"))
    ranks = [entry["rank"] for entry in payload["classes"]]
    assert ranks == list(range(6))
    assert payload["aggregation"]["cross_source_join"] == "forbidden"
    assert payload["aggregation"]["conflicting_outcomes"] == "FAIL"


def test_gate_dependency_graph_is_acyclic() -> None:
    payload = json.loads(DAG.read_text(encoding="utf-8"))
    nodes = set(payload["nodes"])
    edges = [tuple(edge) for edge in payload["edges"]]
    assert all(a in nodes and b in nodes and a != b for a, b in edges)
    outgoing = {node: [] for node in nodes}
    indegree = {node: 0 for node in nodes}
    for left, right in edges:
        outgoing[left].append(right)
        indegree[right] += 1
    queue = [node for node, degree in indegree.items() if degree == 0]
    visited = []
    while queue:
        node = queue.pop()
        visited.append(node)
        for target in outgoing[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    assert set(visited) == nodes
