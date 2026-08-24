"""Deterministic evidence-state features for Predictive Evidence Control (PEC).

The controller is permitted to observe only facts already produced by the retrieval
path.  No model self-confidence, hidden text, wall-clock time or mutable global state
enters this object.  Its canonical fingerprint is therefore suitable for audit,
replay, and deterministic controller decisions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from korpus.application.pec_evidence_features import authority_summary, boundary_for_state, redundancy, score_concentration
from korpus.application.numeric_contracts import finite_number, nonnegative_count
from korpus.application.retrieval_math import tokenize
from korpus.application.risk import QueryRisk, RiskThresholds
from korpus.domain.models import RetrievedEvidence


FEATURE_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class EvidenceState:
    schema_version: int
    query_risk: str
    query_token_count: int
    candidate_count: int
    top1_score: float
    top1_top2_margin: float
    top1_query_coverage: float
    mean_topk_query_coverage: float
    score_concentration: float
    highest_authority_class: str
    top_authority_count: int
    evidence_redundancy: float
    original_query_has_eligible_evidence: bool
    eligible_evidence_count: int
    structural_candidate_exists: bool
    retrieval_gate_passed: bool
    best_score_margin: float
    best_query_coverage_margin: float
    best_authority_margin: float
    minimum_admission_margin: float
    decision_boundary_distance: float
    planner_already_used: bool
    semantic_available: bool
    sparse_dense_overlap: float
    rank_disagreement: float
    inference_cycles_used: int
    inference_evidence_items: int
    inference_conflicts: int

    def canonical_dict(self) -> dict[str, object]:
        return asdict(self)

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def feature_value(self, name: str) -> object:
        if name not in FEATURE_NAMES:
            raise KeyError(f"unknown PEC feature: {name}")
        return getattr(self, name)


FEATURE_NAMES = tuple(
    field
    for field in EvidenceState.__dataclass_fields__
    if field != "schema_version"
)


def feature_schema_sha256() -> str:
    material = json.dumps(
        {"schema_version": FEATURE_SCHEMA_VERSION, "features": FEATURE_NAMES},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _round(value: float) -> float:
    # Canonicalize floating point noise without allowing NaN/Inf to become a boundary value.
    if not finite_number(value):
        raise ValueError("PEC probability feature must be finite")
    return round(max(0.0, min(1.0, float(value))), 12)


def build_evidence_state(
    *,
    query: str,
    risk: QueryRisk,
    evidence: list[RetrievedEvidence],
    eligible_evidence_count: int,
    admission_thresholds: RiskThresholds | None = None,
    planner_already_used: bool = False,
    semantic_available: bool = False,
    sparse_dense_overlap: float = 0.0,
    rank_disagreement: float = 0.0,
    budget_state: Mapping[str, int] | None = None,
) -> EvidenceState:
    """Build one immutable PEC state from observed retrieval facts only."""
    ranked = sorted(
        evidence,
        key=lambda item: (-item.score, -item.query_coverage, item.rank, item.span.ordinal),
    )
    scores = [item.score for item in ranked]
    coverages = [item.query_coverage for item in ranked]
    top1 = scores[0] if scores else 0.0
    top2 = scores[1] if len(scores) > 1 else 0.0
    authority_class, authority_count = authority_summary(ranked)
    semantic_hits = sum(1 for item in ranked if getattr(item, "semantic_score", 0.0) > 0.0)
    lexical_hits = sum(1 for item in ranked if item.lexical_score > 0.0)
    overlap = sparse_dense_overlap
    if semantic_available and sparse_dense_overlap == 0.0 and ranked:
        overlap = min(semantic_hits, lexical_hits) / len(ranked)
    budget = dict(budget_state or {})
    eligible_count = nonnegative_count(eligible_evidence_count)
    if eligible_count is None:
        raise ValueError("eligible_evidence_count must be a non-negative integer")
    budget_defaults = {
        "cycles_used": 0,
        "evidence_items": len(ranked),
        "conflicts": 0,
    }
    parsed_budget: dict[str, int] = {}
    for key, default in budget_defaults.items():
        parsed = nonnegative_count(budget.get(key, default))
        if parsed is None:
            raise ValueError(f"budget_state[{key}] must be a non-negative integer")
        parsed_budget[key] = parsed
    boundary = boundary_for_state(ranked, eligible_count, admission_thresholds)
    return EvidenceState(
        schema_version=FEATURE_SCHEMA_VERSION,
        query_risk=risk.value,
        query_token_count=len(tokenize(query)),
        candidate_count=len(ranked),
        top1_score=_round(top1),
        top1_top2_margin=_round(max(0.0, top1 - top2)),
        top1_query_coverage=_round(coverages[0] if coverages else 0.0),
        mean_topk_query_coverage=_round(sum(coverages) / len(coverages) if coverages else 0.0),
        score_concentration=score_concentration(scores),
        highest_authority_class=authority_class,
        top_authority_count=authority_count,
        evidence_redundancy=redundancy(ranked),
        original_query_has_eligible_evidence=eligible_count > 0,
        eligible_evidence_count=eligible_count,
        structural_candidate_exists=boundary.structural_candidate_exists,
        retrieval_gate_passed=boundary.retrieval_gate_passed,
        best_score_margin=round(boundary.best_score_margin, 12),
        best_query_coverage_margin=round(boundary.best_query_coverage_margin, 12),
        best_authority_margin=round(boundary.best_authority_margin, 12),
        minimum_admission_margin=round(boundary.minimum_admission_margin, 12),
        decision_boundary_distance=round(boundary.decision_boundary_distance, 12),
        planner_already_used=planner_already_used,
        semantic_available=semantic_available,
        sparse_dense_overlap=_round(overlap),
        rank_disagreement=_round(rank_disagreement),
        inference_cycles_used=parsed_budget["cycles_used"],
        inference_evidence_items=parsed_budget["evidence_items"],
        inference_conflicts=parsed_budget["conflicts"],
    )
