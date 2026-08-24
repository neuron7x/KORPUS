"""Bounded feature helpers for PEC evidence-state construction."""
from __future__ import annotations

import math

from korpus.application.evidence_admission import AdmissionBoundarySummary, admission_boundary_summary
from korpus.application.retrieval_math import character_ngrams, jaccard
from korpus.application.risk import RiskThresholds
from korpus.domain.models import RetrievedEvidence


def score_concentration(scores: list[float]) -> float:
    if not scores:
        return 0.0
    if len(scores) == 1:
        return 1.0
    total = sum(max(score, 0.0) for score in scores)
    if total <= 0:
        return 0.0
    probabilities = [max(score, 0.0) / total for score in scores]
    entropy = -sum(p * math.log(p) for p in probabilities if p > 0)
    maximum = math.log(len(probabilities))
    return round(max(0.0, min(1.0, 1.0 - entropy / maximum)), 12) if maximum > 0 else 1.0


def redundancy(evidence: list[RetrievedEvidence]) -> float:
    if len(evidence) < 2:
        return 0.0
    grams = [character_ngrams(item.span.text) for item in evidence]
    maximum = max(
        (jaccard(grams[left], grams[right]) for left in range(len(grams)) for right in range(left + 1, len(grams))),
        default=0.0,
    )
    return round(max(0.0, min(1.0, maximum)), 12)


def authority_summary(evidence: list[RetrievedEvidence]) -> tuple[str, int]:
    if not evidence:
        return "none", 0
    highest = max(item.authority_bonus for item in evidence)
    top = [item for item in evidence if math.isclose(item.authority_bonus, highest, abs_tol=1e-12)]
    return top[0].version.authority.value, len(top)


def boundary_for_state(
    evidence: list[RetrievedEvidence],
    eligible_count: int,
    thresholds: RiskThresholds | None,
) -> AdmissionBoundarySummary:
    if thresholds is None:
        passed = eligible_count > 0
        return AdmissionBoundarySummary(
            bool(evidence), passed,
            0.0 if passed else -1.0,
            0.0 if passed else -1.0,
            0.0 if passed else -1.0,
            0.0 if passed else -1.0,
            0.0 if passed else 1.0,
        )
    boundary = admission_boundary_summary(evidence, thresholds)
    if boundary.retrieval_gate_passed != (eligible_count > 0):
        raise ValueError("PEC admission boundary disagrees with answer eligibility gate")
    return boundary
