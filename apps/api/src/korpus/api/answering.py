"""Answering, bounded — in one place, because there is more than one door to it.

`POST /v1/answers` has always acquired the admission controller before retrieval: a global
concurrency bound, and inside it a per-subject share so one reader cannot take the whole
service. ACT-001 added a second door — `POST /v1/conversations/{id}/ask` — and it went
straight to `ExtractiveAnswerService.execute`.

Nothing failed. The gate stayed green, the metric kept reporting, and the control was
simply not on the path the browser had started using: the conversation route became the
default the moment the interface had a conversation panel. So the bound that exists to stop
one account saturating a hundred-thousand-span retrieval was, in practice, off — and off in
the way that is hardest to see, because the *other* route still had it.

That is why this is a module and not a copied block. Two copies drifted once; three would
drift again. `test_answer_paths_are_bounded.py` reads the route table and asserts that every
function reaching `execute` goes through here, so a fourth door cannot be added without the
bound.
"""

from __future__ import annotations

from contextlib import nullcontext  # noqa: F401  (the mutation catalogue substitutes it)

from fastapi import HTTPException

from korpus.api.overload_http import overload_http_exception
from korpus.application.answer_query import ExtractiveAnswerService
from korpus.application.resilience import AdmissionController, OverloadedError
from korpus.application.pec_metrics_context import reset_pec_observer, set_pec_observer
from korpus.domain.models import Answer, Identity, QueryRequest
from korpus.infrastructure.observability import Observability


def bounded_answer(
    service: ExtractiveAnswerService,
    identity: Identity,
    query: QueryRequest,
    admission: AdmissionController,
    observability: Observability,
) -> Answer:
    """One answer, inside the concurrency bound, with the metrics that go with it.

    The active gauge is set in a `finally` so a refused or failed request still leaves the
    number describing reality. A gauge that only decrements on the happy path drifts
    upward under exactly the load it exists to report on.
    """
    pec_token = set_pec_observer(observability.pec.observe)
    try:
        with admission.acquire(identity.subject):
            observability.answer_admission_active.set(admission.snapshot().active)
            with observability.measure_retrieval():
                answer = service.execute(identity, query)
    finally:
        reset_pec_observer(pec_token)
        observability.answer_admission_active.set(admission.snapshot().active)

    from korpus.application.risk import classify_query_risk

    observability.observe_answer(
        answer.status.value, answer.decision_reason, classify_query_risk(query.text).value
    )
    return answer

def overloaded(error: OverloadedError) -> HTTPException:
    """Compatibility seam: all answer doors share the canonical overload mapper."""
    return overload_http_exception(error)
__all__ = ["AdmissionController", "OverloadedError", "bounded_answer", "overloaded"]
