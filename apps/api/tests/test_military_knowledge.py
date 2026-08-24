from __future__ import annotations

from datetime import date

import pytest
from korpus.application.military_knowledge import (
    EvidenceBinding,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeRelation,
    KnowledgeRelationKind,
    MilitaryKnowledgeGraph,
    RevisionChangeKind,
    RevisionUnit,
    revision_diff,
)
from pydantic import ValidationError


def binding(*, until: date | None = None) -> EvidenceBinding:
    return EvidenceBinding(
        document_id="doc-1",
        version_id="version-1",
        span_ids=frozenset({"span-1"}),
        source_hash="a" * 64,
        effective_from=date(2026, 1, 1),
        effective_until=until,
    )


def node(node_id: str, kind: KnowledgeNodeKind = KnowledgeNodeKind.DOCTRINE) -> KnowledgeNode:
    return KnowledgeNode(id=node_id, kind=kind, label=node_id, bindings=(binding(),))


def test_graph_is_source_bound_and_publishable() -> None:
    graph = MilitaryKnowledgeGraph(
        nodes=(node("doctrine.a"), node("procedure.a", KnowledgeNodeKind.PROCEDURE)),
        relations=(
            KnowledgeRelation(
                source_id="doctrine.a",
                target_id="procedure.a",
                kind=KnowledgeRelationKind.GOVERNS,
                bindings=(binding(),),
            ),
        ),
    )
    assert graph.publication_violations(as_of=date(2026, 8, 20)) == ()


def test_graph_fails_on_dangling_relation() -> None:
    with pytest.raises(ValidationError, match="unknown nodes"):
        MilitaryKnowledgeGraph(
            nodes=(node("doctrine.a"),),
            relations=(
                KnowledgeRelation(
                    source_id="doctrine.a",
                    target_id="missing.node",
                    kind=KnowledgeRelationKind.GOVERNS,
                    bindings=(binding(),),
                ),
            ),
        )


def test_graph_fails_closed_when_all_evidence_is_stale() -> None:
    expired = binding(until=date(2026, 8, 19))
    graph = MilitaryKnowledgeGraph(
        nodes=(
            KnowledgeNode(
                id="doctrine.a",
                kind=KnowledgeNodeKind.DOCTRINE,
                label="A",
                bindings=(expired,),
            ),
        )
    )
    assert graph.publication_violations(as_of=date(2026, 8, 20)) == (
        "node_without_effective_evidence:doctrine.a",
    )


def test_supersession_cycle_is_a_publication_blocker() -> None:
    graph = MilitaryKnowledgeGraph(
        nodes=(node("a"), node("b")),
        relations=(
            KnowledgeRelation(
                source_id="a",
                target_id="b",
                kind=KnowledgeRelationKind.SUPERSEDES,
                bindings=(binding(),),
            ),
            KnowledgeRelation(
                source_id="b",
                target_id="a",
                kind=KnowledgeRelationKind.SUPERSEDES,
                bindings=(binding(),),
            ),
        ),
    )
    assert any(
        item.startswith("supersession_cycle:")
        for item in graph.publication_violations(as_of=date(2026, 8, 20))
    )


def test_revision_diff_is_exact_hash_bound_and_deterministic() -> None:
    old = [
        RevisionUnit(0, "Крок один."),
        RevisionUnit(1, "Крок два."),
        RevisionUnit(2, "Крок три."),
    ]
    new = [
        RevisionUnit(0, "Крок один."),
        RevisionUnit(1, "Крок два змінено."),
        RevisionUnit(2, "Крок три."),
    ]
    first = revision_diff(old, new)
    second = revision_diff(old, new)
    assert first == second
    assert first.changed
    assert first.changed_units == 1
    replaced = next(item for item in first.changes if item.kind is RevisionChangeKind.REPLACED)
    assert replaced.old_text == ("Крок два.",)
    assert replaced.new_text == ("Крок два змінено.",)
    assert replaced.old_hashes[0] != replaced.new_hashes[0]


def test_revision_diff_ignores_only_unicode_whitespace_representation() -> None:
    old = [RevisionUnit(0, "A  B")]
    new = [RevisionUnit(0, "A\u00a0B")]
    result = revision_diff(old, new)
    assert not result.changed
    assert result.changes[0].kind is RevisionChangeKind.UNCHANGED


def test_effective_neighborhood_is_bounded_and_filters_expired_relations():
    from datetime import date

    from korpus.application.military_knowledge import effective_neighborhood

    binding = EvidenceBinding(
        document_id="d",
        version_id="v",
        span_ids=frozenset({"s"}),
        source_hash="a" * 64,
        effective_from=date(2026, 1, 1),
    )
    expired = EvidenceBinding(
        document_id="d",
        version_id="old",
        span_ids=frozenset({"s2"}),
        source_hash="b" * 64,
        effective_until=date(2025, 12, 31),
    )
    graph = MilitaryKnowledgeGraph(
        nodes=(
            KnowledgeNode(id="a", kind=KnowledgeNodeKind.DOCTRINE, label="A", bindings=(binding,)),
            KnowledgeNode(id="b", kind=KnowledgeNodeKind.PROCEDURE, label="B", bindings=(binding,)),
            KnowledgeNode(id="c", kind=KnowledgeNodeKind.TERM, label="C", bindings=(binding,)),
        ),
        relations=(
            KnowledgeRelation(
                source_id="a",
                target_id="b",
                kind=KnowledgeRelationKind.GOVERNS,
                bindings=(binding,),
            ),
            KnowledgeRelation(
                source_id="b",
                target_id="c",
                kind=KnowledgeRelationKind.DEFINES,
                bindings=(expired,),
            ),
        ),
    )
    assert effective_neighborhood(graph, "a", as_of=date(2026, 8, 20), max_depth=2) == ("a", "b")


def test_precomputed_graph_index_is_exactly_equivalent_to_direct_traversal():
    from datetime import date

    from korpus.application.military_knowledge import EffectiveGraphIndex, effective_neighborhood

    binding = EvidenceBinding(
        document_id="d", version_id="v", span_ids=frozenset({"s"}), source_hash="c" * 64
    )
    nodes = tuple(
        KnowledgeNode(id=f"n{i}", kind=KnowledgeNodeKind.TERM, label=f"N{i}", bindings=(binding,))
        for i in range(8)
    )
    relations = tuple(
        KnowledgeRelation(
            source_id=f"n{i}",
            target_id=f"n{i + 1}",
            kind=KnowledgeRelationKind.DEFINES,
            bindings=(binding,),
        )
        for i in range(7)
    )
    graph = MilitaryKnowledgeGraph(nodes=nodes, relations=relations)
    observed = date(2026, 8, 20)
    index = EffectiveGraphIndex.build(graph, as_of=observed)
    for depth in range(0, 8):
        assert index.neighborhood("n0", max_depth=depth) == effective_neighborhood(
            graph, "n0", as_of=observed, max_depth=depth
        )
