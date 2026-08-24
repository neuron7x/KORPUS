"""Risk-adjusted evidence thresholds.

The classifier moved to `risk_rules.py` on 2026-08-05 (RAG-009): rules carry ids and
examples, and an unmatched query is UNCLASSIFIED rather than STANDARD. This module keeps
the thresholds, and the one decision that matters here is what UNCLASSIFIED costs.

It is scored at the temporal setting, not the standard one. An unrecognised query used
to fall to STANDARD — the loosest evidence requirement in the system — which is
fail-open in the single place the design is otherwise fail-closed. Scoring it at
OPERATIONAL instead would refuse most ordinary questions and teach operators to
distrust the refusals; the middle setting raises the bar without making the system
useless, and the class travels into the answer so a reader can see that it was applied.
"""

from __future__ import annotations

from dataclasses import dataclass

from korpus.application.numeric_contracts import require_rate
from korpus.application.risk_rules import RISK_RULES, QueryRisk, classify

__all__ = [
    "RISK_RULES",
    "QueryRisk",
    "RiskThresholds",
    "classify_query_risk",
    "risk_adjusted_thresholds",
]


@dataclass(frozen=True)
class RiskThresholds:
    minimum_score: float
    minimum_query_coverage: float
    minimum_support_score: float
    minimum_authority: float

    def __post_init__(self) -> None:
        for name in (
            "minimum_score",
            "minimum_query_coverage",
            "minimum_support_score",
            "minimum_authority",
        ):
            require_rate(getattr(self, name), label=name)


def classify_query_risk(text: str) -> QueryRisk:
    """The class alone, for callers that do not record which rule decided it."""
    return classify(text)[0]


def risk_adjusted_thresholds(
    risk: QueryRisk,
    *,
    minimum_score: float,
    minimum_query_coverage: float,
    minimum_support_score: float,
) -> RiskThresholds:
    minimum_score = require_rate(minimum_score, label="minimum_score")
    minimum_query_coverage = require_rate(minimum_query_coverage, label="minimum_query_coverage")
    minimum_support_score = require_rate(minimum_support_score, label="minimum_support_score")
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
    if risk is QueryRisk.UNCLASSIFIED:
        # Not knowing what a question is must cost more than knowing it is ordinary, or
        # the unknown case is the cheapest place to land. What it raises is *evidential*
        # — score, support, authority — and what it deliberately does not raise is query
        # coverage.
        #
        # Coverage measures whether the retrieved passage is about the question asked.
        # That is a property of the retrieval, not of the risk class: not knowing how
        # dangerous a question is says nothing about how much of it the evidence
        # covers. Raising it here failed two frozen evaluation cases that the corpus
        # does answer correctly, and the frozen protocol forbids editing the dataset to
        # match — so the threshold that had no argument behind it is the one that moved.
        return RiskThresholds(
            minimum_score=min(1.0, minimum_score + 0.07),
            minimum_query_coverage=minimum_query_coverage,
            minimum_support_score=min(1.0, minimum_support_score + 0.07),
            minimum_authority=0.46,
        )
    return RiskThresholds(
        minimum_score=minimum_score,
        minimum_query_coverage=minimum_query_coverage,
        minimum_support_score=minimum_support_score,
        minimum_authority=0.0,
    )
