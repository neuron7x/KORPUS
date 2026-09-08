"""Телеметрія спроможностей: виміри обмежені, і кожна межа пройдена.

Мітки Prometheus — це декартів добуток: неограничене значення в мітці робить із метрики
пам'ять про кожен запит. Тому клас звужує все, що приходить ззовні. Виміряно
08.09.2026: три непокриті гілки, і всі три — саме ці звуження.
"""

from __future__ import annotations

from uuid import UUID

from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.invoke import IntegrationResult
from korpus.infrastructure.capability_observability import CapabilityObservability
from korpus.infrastructure.observability import Observability
from prometheus_client import CollectorRegistry

from apps.api.tests.test_capability_gateway_http_adapter import _spec


def _telemetry() -> tuple[CapabilityObservability, Observability]:
    observability = Observability(registry=CollectorRegistry(auto_describe=True))
    return CapabilityObservability(observability), observability


def test_a_span_for_an_unresolved_capability_carries_the_fact_that_it_is_unresolved() -> None:
    """Спроможність не впізнано — проліт усе одно є, і він каже саме це."""
    telemetry, observability = _telemetry()
    with telemetry.invocation_span(None):
        pass
    observability.close()


def test_a_span_for_a_resolved_capability_carries_its_exact_identity() -> None:
    """Негативний контроль: проліт не порожній, коли спроможність відома."""
    telemetry, observability = _telemetry()
    with telemetry.invocation_span(_spec()):
        pass
    observability.close()


def test_an_absent_error_code_becomes_the_bounded_label_none() -> None:
    """`None` — не порожній рядок і не пропуск мітки: у метриці це окреме значення."""
    telemetry, observability = _telemetry()
    telemetry.observe_invocation(
        spec=_spec(),
        result=IntegrationResult(
            invocation_id=UUID("66666666-6666-6666-6666-666666666666"),
            outcome=InvocationOutcome.SUCCESS,
            error_code=None,
            audit_record_id="audit-1",
        ),
        duration_seconds=0.01,
    )
    exposition = observability.export_prometheus().decode("utf-8")
    assert 'error_code="none"' in exposition
    observability.close()
