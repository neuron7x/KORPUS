"""Fail-closed post-retrieval admission gate for extractive answering."""
from __future__ import annotations

from typing import Any


def apply_retrieval_gate(
    service: Any,
    *,
    identity: Any,
    query: Any,
    release_id: str,
    corpora: frozenset[str],
    retrieved: list[Any],
    risk: Any,
    plan: Any,
    pec_trace: Any,
    early_abstain: bool,
) -> tuple[Any | None, list[Any] | None]:
    breaches = service._scope_breaches(identity, corpora, retrieved)
    if breaches:
        answer = service._breach(release_id, breaches)
        service._audit(identity, query, answer, retrieved, [], risk, breaches=breaches, plan=plan, pec_trace=pec_trace)
        return answer, None
    if early_abstain:
        answer = service._abstain(
            release_id,
            "pec_controller_abstain",
            "Калібрований контролер зупинив відповідь для цього стану доказів.",
            max((item.score for item in retrieved), default=0.0),
        )
        service._audit(identity, query, answer, retrieved, [], risk, plan=plan, pec_trace=pec_trace)
        return answer, None
    eligible = service.answer_policy.eligible(retrieved, risk)
    if not eligible:
        answer = service._abstain(
            release_id,
            "retrieval_gate_failed",
            "У чинному перевіреному корпусі недостатньо доказів для надійної відповіді.",
            max((item.score for item in retrieved), default=0.0),
        )
        service._audit(identity, query, answer, retrieved, eligible, risk, plan=plan, pec_trace=pec_trace)
        return answer, eligible
    return None, eligible
