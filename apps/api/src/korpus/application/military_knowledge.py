"""Source-bound military knowledge primitives.

This module intentionally does not introduce an autonomous agent or a second truth store.
It projects already-authorized corpus evidence into two deterministic capabilities:

* a small doctrine/learning knowledge graph whose every node is bound to exact evidence;
* an exact structural revision diff for doctrine/procedure text.

Both are deliberately inference-free.  They are safe building blocks for navigation,
training and change review because they can explain *where* a relation/change came from
without inventing military facts.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KnowledgeNodeKind(StrEnum):
    DOCTRINE = "doctrine"
    PROCEDURE = "procedure"
    TERM = "term"
    EQUIPMENT = "equipment"
    ROLE = "role"
    TRAINING_OBJECTIVE = "training_objective"


class KnowledgeRelationKind(StrEnum):
    DEFINES = "defines"
    GOVERNS = "governs"
    REQUIRES = "requires"
    APPLIES_TO = "applies_to"
    TRAINS = "trains"
    SUPERSEDES = "supersedes"


class EvidenceBinding(BaseModel):
    """Exact corpus evidence that licenses one graph assertion."""

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(min_length=1, max_length=128)
    version_id: str = Field(min_length=1, max_length=128)
    span_ids: frozenset[str] = Field(min_length=1, max_length=128)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    effective_from: date | None = None
    effective_until: date | None = None

    def effective_on(self, observed: date) -> bool:
        return (self.effective_from is None or self.effective_from <= observed) and (
            self.effective_until is None or observed <= self.effective_until
        )


class KnowledgeNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    kind: KnowledgeNodeKind
    label: str = Field(min_length=1, max_length=300)
    bindings: tuple[EvidenceBinding, ...] = Field(min_length=1, max_length=64)


class KnowledgeRelation(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    target_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    kind: KnowledgeRelationKind
    bindings: tuple[EvidenceBinding, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def reject_self_relation(self) -> KnowledgeRelation:
        if self.source_id == self.target_id:
            raise ValueError("knowledge relation cannot target itself")
        return self


class MilitaryKnowledgeGraph(BaseModel):
    """A deterministic source-bound semantic layer over corpus evidence.

    The graph is not allowed to repair itself.  Dangling links, duplicate identities,
    expired evidence and supersession cycles are publication blockers.
    """

    model_config = ConfigDict(frozen=True)

    nodes: tuple[KnowledgeNode, ...] = Field(default_factory=tuple, max_length=100_000)
    relations: tuple[KnowledgeRelation, ...] = Field(default_factory=tuple, max_length=500_000)

    @model_validator(mode="after")
    def validate_identity(self) -> MilitaryKnowledgeGraph:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("knowledge node ids must be unique")
        keys = [(item.source_id, item.target_id, item.kind) for item in self.relations]
        if len(keys) != len(set(keys)):
            raise ValueError("knowledge relation identities must be unique")
        known = set(node_ids)
        dangling = sorted(
            {
                node_id
                for relation in self.relations
                for node_id in (relation.source_id, relation.target_id)
                if node_id not in known
            }
        )
        if dangling:
            raise ValueError(f"knowledge relations reference unknown nodes: {dangling}")
        return self

    def publication_violations(self, *, as_of: date) -> tuple[str, ...]:
        violations: set[str] = set()
        for node in self.nodes:
            if not any(binding.effective_on(as_of) for binding in node.bindings):
                violations.add(f"node_without_effective_evidence:{node.id}")
        for relation in self.relations:
            if not any(binding.effective_on(as_of) for binding in relation.bindings):
                violations.add(
                    f"relation_without_effective_evidence:{relation.source_id}:"
                    f"{relation.kind}:{relation.target_id}"
                )

        supersedes: dict[str, set[str]] = {node.id: set() for node in self.nodes}
        for relation in self.relations:
            if relation.kind is KnowledgeRelationKind.SUPERSEDES:
                supersedes[relation.source_id].add(relation.target_id)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                violations.add(f"supersession_cycle:{node_id}")
                return
            if node_id in visited:
                return
            visiting.add(node_id)
            for target in sorted(supersedes[node_id]):
                visit(target)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in sorted(supersedes):
            visit(node_id)
        return tuple(sorted(violations))


class RevisionChangeKind(StrEnum):
    UNCHANGED = "unchanged"
    ADDED = "added"
    REMOVED = "removed"
    REPLACED = "replaced"


@dataclass(frozen=True)
class RevisionUnit:
    ordinal: int
    text: str

    @property
    def normalized(self) -> str:
        return " ".join(unicodedata.normalize("NFKC", self.text).split())

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RevisionChange:
    kind: RevisionChangeKind
    old_ordinals: tuple[int, ...]
    new_ordinals: tuple[int, ...]
    old_text: tuple[str, ...]
    new_text: tuple[str, ...]
    old_hashes: tuple[str, ...]
    new_hashes: tuple[str, ...]


@dataclass(frozen=True)
class RevisionDiff:
    changes: tuple[RevisionChange, ...]

    @property
    def changed(self) -> bool:
        return any(change.kind is not RevisionChangeKind.UNCHANGED for change in self.changes)

    @property
    def changed_units(self) -> int:
        return sum(
            max(len(change.old_ordinals), len(change.new_ordinals))
            for change in self.changes
            if change.kind is not RevisionChangeKind.UNCHANGED
        )


def revision_diff(old: Iterable[RevisionUnit], new: Iterable[RevisionUnit]) -> RevisionDiff:
    """Return a deterministic structural diff without semantic inference.

    Equality uses NFKC + whitespace normalization only.  The report always carries the
    original text and SHA-256 hashes, so a reviewer can verify every reported change.
    """
    from difflib import SequenceMatcher

    old_items = tuple(sorted(old, key=lambda item: item.ordinal))
    new_items = tuple(sorted(new, key=lambda item: item.ordinal))
    old_norm = [item.normalized for item in old_items]
    new_norm = [item.normalized for item in new_items]
    matcher = SequenceMatcher(a=old_norm, b=new_norm, autojunk=False)
    output: list[RevisionChange] = []
    map_kind = {
        "equal": RevisionChangeKind.UNCHANGED,
        "insert": RevisionChangeKind.ADDED,
        "delete": RevisionChangeKind.REMOVED,
        "replace": RevisionChangeKind.REPLACED,
    }
    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        left = old_items[i1:i2]
        right = new_items[j1:j2]
        output.append(
            RevisionChange(
                kind=map_kind[opcode],
                old_ordinals=tuple(item.ordinal for item in left),
                new_ordinals=tuple(item.ordinal for item in right),
                old_text=tuple(item.text for item in left),
                new_text=tuple(item.text for item in right),
                old_hashes=tuple(item.text_hash for item in left),
                new_hashes=tuple(item.text_hash for item in right),
            )
        )
    return RevisionDiff(changes=tuple(output))


def effective_neighborhood(
    graph: MilitaryKnowledgeGraph,
    start_id: str,
    *,
    as_of: date,
    max_depth: int = 2,
    relation_kinds: frozenset[KnowledgeRelationKind] | None = None,
) -> tuple[str, ...]:
    """Bounded deterministic traversal over relations with currently effective evidence.

    The traversal is intentionally small and fail-closed: expired relations are invisible,
    unknown starts fail, and callers must opt into deeper walks rather than receive an
    unbounded graph expansion.
    """
    if max_depth < 0 or max_depth > 8:
        raise ValueError("max_depth must be between 0 and 8")
    nodes = {node.id: node for node in graph.nodes}
    if start_id not in nodes:
        raise KeyError(start_id)
    allowed = relation_kinds or frozenset(KnowledgeRelationKind)
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for relation in graph.relations:
        if relation.kind not in allowed:
            continue
        if any(binding.effective_on(as_of) for binding in relation.bindings):
            adjacency[relation.source_id].add(relation.target_id)
    seen = {start_id}
    frontier = {start_id}
    for _ in range(max_depth):
        frontier = {
            target
            for source in sorted(frontier)
            for target in adjacency[source]
            if target not in seen
        }
        if not frontier:
            break
        seen.update(frontier)
    return tuple(sorted(seen))


@dataclass(frozen=True)
class EffectiveGraphIndex:
    """Precomputed immutable adjacency for repeated same-date graph navigation."""

    as_of: date
    node_ids: frozenset[str]
    adjacency: dict[KnowledgeRelationKind, dict[str, frozenset[str]]]

    @classmethod
    def build(cls, graph: MilitaryKnowledgeGraph, *, as_of: date) -> EffectiveGraphIndex:
        node_ids = frozenset(node.id for node in graph.nodes)
        mutable: dict[KnowledgeRelationKind, dict[str, set[str]]] = {
            kind: {node_id: set() for node_id in node_ids} for kind in KnowledgeRelationKind
        }
        for relation in graph.relations:
            if any(binding.effective_on(as_of) for binding in relation.bindings):
                mutable[relation.kind][relation.source_id].add(relation.target_id)
        frozen = {
            kind: {source: frozenset(targets) for source, targets in rows.items()}
            for kind, rows in mutable.items()
        }
        return cls(as_of=as_of, node_ids=node_ids, adjacency=frozen)

    def neighborhood(
        self,
        start_id: str,
        *,
        max_depth: int = 2,
        relation_kinds: frozenset[KnowledgeRelationKind] | None = None,
    ) -> tuple[str, ...]:
        if max_depth < 0 or max_depth > 8:
            raise ValueError("max_depth must be between 0 and 8")
        if start_id not in self.node_ids:
            raise KeyError(start_id)
        allowed = relation_kinds or frozenset(KnowledgeRelationKind)
        seen = {start_id}
        frontier = {start_id}
        for _ in range(max_depth):
            next_frontier: set[str] = set()
            for source in frontier:
                for kind in allowed:
                    next_frontier.update(self.adjacency[kind][source])
            next_frontier.difference_update(seen)
            if not next_frontier:
                break
            seen.update(next_frontier)
            frontier = next_frontier
        return tuple(sorted(seen))
