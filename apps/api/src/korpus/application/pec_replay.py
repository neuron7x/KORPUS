"""Offline counterfactual replay/oracle primitives for PEC."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from korpus.application.numeric_contracts import finite_number, nonnegative_count

from korpus.application.pec_oracle_policy import OracleDecision, dominates, solve_oracle
from korpus.application.predictive_evidence_control import RetrievalAction
RESOURCE_FIELDS = (
    "latency_ms",
    "search_count",
    "planner_calls",
    "semantic_calls",
    "candidate_count",
    "external_tokens",
    "provider_cost_microunits",
)

@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    query_id: str
    group_id: str
    action: RetrievalAction
    state_fingerprint: str
    features: Mapping[str, object]
    authorization_ok: bool
    answer_error: bool
    quality_ok: bool
    answer_status: str
    gold_hit: bool
    latency_ms: float
    search_count: int
    planner_calls: int
    semantic_calls: int
    candidate_count: int
    external_tokens: int
    provider_cost_microunits: int
    decision_reason: str = ""
    evidence_fingerprints: tuple[str, ...] = ()
    corpus_release_id: str = ""
    evaluation_protocol_sha256: str = ""
    answer_calibration_id: str = ""
    risk_class: str = ""
    judgment: str = ""
    retrieved_spans: tuple[tuple[str, int], ...] = ()
    retrieval_quality: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("authorization_ok", "answer_error", "quality_ok", "gold_hit"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        if not finite_number(self.latency_ms) or float(self.latency_ms) < 0.0:
            raise ValueError("latency_ms must be a finite non-negative number")
        for name in RESOURCE_FIELDS[1:]:
            value = getattr(self, name)
            if nonnegative_count(value) is None:
                raise ValueError(f"{name} must be a non-negative integer")
        for name, value in self.retrieval_quality.items():
            if not isinstance(name, str) or not name:
                raise ValueError("retrieval_quality metric names must be non-empty strings")
            if not finite_number(value):
                raise ValueError(f"retrieval_quality[{name}] must be finite")
        for span_id, rank in self.retrieved_spans:
            if not span_id:
                raise ValueError("retrieved span ids must be non-empty")
            if nonnegative_count(rank) is None or rank < 1:
                raise ValueError("retrieved span rank must be a positive integer")
    def resources(self) -> tuple[float, ...]:
        return tuple(float(getattr(self, name)) for name in RESOURCE_FIELDS)
    def admissible(self) -> bool:
        return self.authorization_ok and not self.answer_error and self.quality_ok
    def decision_signature(self) -> tuple[str, str]:
        return self.answer_status, self.decision_reason

def replay_priority(row: Mapping[str, object]) -> tuple[object, ...]:
    """Lexicographic replay priority: safety before error before compute residual."""
    flags: list[bool] = []
    for field in (
        "authorization_violation", "accepted_answer_error", "false_abstention",
        "controller_oracle_disagreement", "out_of_support",
    ):
        value = row.get(field, False)
        if not isinstance(value, bool):
            raise ValueError(f"{field} must be boolean")
        flags.append(value)
    residual = row.get("retrieval_benefit_residual", 0.0)
    if not finite_number(residual):
        raise ValueError("retrieval_benefit_residual must be finite")
    return (
        0 if flags[0] else 1,
        0 if flags[1] else 1,
        0 if flags[2] else 1,
        0 if flags[3] else 1,
        -abs(float(residual)),
        0 if flags[4] else 1,
        str(row.get("query_id", "")),
    )

def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()
