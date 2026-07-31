from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from korpus.application.retrieval import normalize_text


class QueryRisk(StrEnum):
    STANDARD = "standard"
    TEMPORAL = "temporal"
    OPERATIONAL = "operational"


TEMPORAL_PATTERNS = (
    re.compile(r"\b(чинн|діє|строк|дата|редакц|скасован|на сьогодні|станом на)"),
    re.compile(r"\b(valid|effective|current|as of|deadline|revision)\b"),
)
OPERATIONAL_PATTERNS = (
    re.compile(r"\b(наказ|процедур|порядок дій|зобовязан|обовязков|дозволен|заборонен)"),
    re.compile(r"\b(order|procedure|must|shall|required|prohibited|authorized)\b"),
)


@dataclass(frozen=True)
class RiskThresholds:
    minimum_score: float
    minimum_query_coverage: float
    minimum_support_score: float
    minimum_authority: float


def classify_query_risk(text: str) -> QueryRisk:
    normalized = normalize_text(text).replace("’", "'")
    if any(pattern.search(normalized) for pattern in OPERATIONAL_PATTERNS):
        return QueryRisk.OPERATIONAL
    if any(pattern.search(normalized) for pattern in TEMPORAL_PATTERNS):
        return QueryRisk.TEMPORAL
    return QueryRisk.STANDARD


def risk_adjusted_thresholds(
    risk: QueryRisk,
    *,
    minimum_score: float,
    minimum_query_coverage: float,
    minimum_support_score: float,
) -> RiskThresholds:
    if risk is QueryRisk.OPERATIONAL:
        return RiskThresholds(
            minimum_score=min(1.0, minimum_score + 0.12),
            minimum_query_coverage=min(1.0, minimum_query_coverage + 0.15),
            minimum_support_score=min(1.0, minimum_support_score + 0.12),
            minimum_authority=0.74,
        )
    if risk is QueryRisk.TEMPORAL:
        return RiskThresholds(
            minimum_score=min(1.0, minimum_score + 0.07),
            minimum_query_coverage=min(1.0, minimum_query_coverage + 0.10),
            minimum_support_score=min(1.0, minimum_support_score + 0.07),
            minimum_authority=0.46,
        )
    return RiskThresholds(
        minimum_score=minimum_score,
        minimum_query_coverage=minimum_query_coverage,
        minimum_support_score=minimum_support_score,
        minimum_authority=0.0,
    )
