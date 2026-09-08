"""Проєкція КОЖНОГО роду відмови виконання в наслідок і код.

`CapabilityExecutor` розрізняє три речі, які легко злити в одну: дію, якої НЕ БУЛО
(`AdapterKnownNoEffect`), дію з невідомим наслідком (`AdapterOutcomeUnknown`) і збій уже
після відправки (`AdapterExecutionFailed`). Помилка на цьому розрізненні коштує
подвійного побічного ефекту або втраченої неоднозначності — тому кожна гілка тут має
власний вхід. Виміряно 08.09.2026: непокритими лишались саме ці проєкції.

Фікстури беруться з `test_capability_gateway_adapter_result_boundary`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from korpus.application.capability_gateway.adapters import (
    AdapterExecutionFailed,
    AdapterExecutionResult,
    AdapterKnownNoEffect,
)
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.contracts import payload_digest
from korpus.application.capability_gateway.effects import EffectGuard, EffectState
from korpus.application.capability_gateway.evidence import (
    EvidenceBinding,
    EvidenceEnvelope,
    EvidenceProvenance,
    EvidenceStatus,
    ProvenanceKind,
)
from korpus.application.capability_gateway.result import IntegrationResult
from korpus.application.capability_gateway.types import (
    CapabilitySpec,
    EffectClass,
    EvidenceProfile,
    EvidenceSpec,
)

from apps.api.tests.test_capability_gateway_adapter_result_boundary import (
    _Audit,
    _context,
    _Effects,
    _executor,
    _frame,
    _request,
    _spec,
)


class _RaisingAdapter:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def execute(self, **kwargs: object) -> AdapterExecutionResult:
        del kwargs
        self.calls += 1
        raise self.error


class _FixedOutputAdapter:
    def __init__(self, output: object, evidence: object | None = None) -> None:
        self.output = output
        self.evidence = evidence
        self.calls = 0

    def execute(self, **kwargs: object) -> AdapterExecutionResult:
        del kwargs
        self.calls += 1
        return AdapterExecutionResult(output=self.output, evidence=self.evidence)  # type: ignore[arg-type]


def _run(
    adapter: object,
    *,
    spec: CapabilitySpec | None = None,
    guard: EffectGuard | None = None,
    schemas: object | None = None,
) -> tuple[IntegrationResult, _Effects, _Audit]:
    resolved = spec or _spec(EffectClass.READ_LOCAL)
    effects, audit = _Effects(), _Audit()
    executor = _executor(adapter, effects, audit)
    if schemas is not None:
        executor._schemas = schemas  # type: ignore[assignment]
    result = executor.execute(
        _frame(resolved, _request()),
        guard
        or EffectGuard(required=False, should_execute=True, binding_digest=None, reservation=None),
    )
    return result, effects, audit


def test_an_adapter_that_proves_no_effect_happened_projects_a_plain_failure() -> None:
    """«Дії не було» — найсильніше твердження адаптера: воно ЗАКРИВАЄ неоднозначність."""
    adapter = _RaisingAdapter(AdapterKnownNoEffect("provider rejected before dispatch"))

    result, effects, audit = _run(adapter)

    assert adapter.calls == 1
    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "ADAPTER_FAILURE"
    assert effects.targets == []
    assert audit.calls == 1


def test_a_declared_execution_failure_projects_a_plain_failure_for_a_read() -> None:
    """Збій читання нічого не лишає позаду — переводити його в OUTCOME_UNKNOWN зайве."""
    adapter = _RaisingAdapter(AdapterExecutionFailed("provider returned 500"))

    result, _, _ = _run(adapter)

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "ADAPTER_FAILURE"


def test_a_declared_execution_failure_on_a_guarded_read_still_closes_the_reservation() -> None:
    """Резервація існує навіть у неефектної спроможності: її треба ЗАКРИТИ, не лишити PENDING."""
    from korpus.application.capability_gateway.effects import EffectReservation

    from apps.api.tests.test_capability_gateway_adapter_result_boundary import _record

    record = _record()
    adapter = _RaisingAdapter(AdapterExecutionFailed("provider returned 500"))

    result, effects, _ = _run(
        adapter,
        guard=EffectGuard(
            required=True,
            should_execute=True,
            binding_digest=record.binding_digest,
            reservation=EffectReservation(record=record, created=True),
        ),
    )

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "ADAPTER_FAILURE"
    assert effects.targets == [EffectState.FAILED_KNOWN_NO_EFFECT]


def test_an_output_validator_that_fails_in_an_unnamed_way_is_an_internal_error() -> None:
    """Валідатор — впорскуваний порт; його власна аварія не є вадою СХЕМИ відповіді."""

    class _Exploding:
        def validate(self, schema_id: str, value: object) -> None:
            del value
            if schema_id.endswith("output:v1"):
                raise RuntimeError("validator backend is misconfigured")

    result, _, _ = _run(_FixedOutputAdapter({"value": "ok"}), schemas=_Exploding())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "INTERNAL_ERROR"


def test_output_that_is_not_canonical_json_is_a_schema_fault() -> None:
    """Схема пропустила, а закодувати не вдалося: вада у ВІДПОВІДІ, не в нас."""
    result, _, _ = _run(_FixedOutputAdapter({"value": {1, 2}}))

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "OUTPUT_SCHEMA_INVALID"


def test_output_over_the_declared_ceiling_is_refused() -> None:
    """Стеля відповіді оголошена спроможністю; провайдер її не рухає."""
    result, _, _ = _run(_FixedOutputAdapter({"value": "x" * 8192}))

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "OUTPUT_SCHEMA_INVALID"


def test_output_at_the_ceiling_is_accepted() -> None:
    """Негативний контроль: карається ПЕРЕВИЩЕННЯ, не сам розмір."""
    result, _, _ = _run(_FixedOutputAdapter({"value": "x" * 16}))

    assert result.outcome is InvocationOutcome.SUCCESS


def _evidence_spec(**overrides: object) -> CapabilitySpec:
    base = _spec(EffectClass.READ_LOCAL)
    return base.model_copy(update={"evidence": EvidenceSpec(**overrides)})  # type: ignore[arg-type]


def _envelope(output: object, *, observed_at: datetime) -> EvidenceEnvelope:
    context = _context()
    spec = _spec(EffectClass.READ_LOCAL)
    return EvidenceEnvelope(
        schema_version="korpus.evidence-envelope.v1",
        status=EvidenceStatus.VALID,
        binding=EvidenceBinding(
            invocation_id=context.invocation_id,
            capability_id=spec.capability_id,
            capability_version=spec.version,
            adapter_id=spec.adapter.adapter_id,
            adapter_version=spec.adapter.adapter_version,
            output_digest=payload_digest(output),
        ),
        provenance=EvidenceProvenance(kind=ProvenanceKind.INTERNAL),
        observed_at=observed_at,
    )


def test_evidence_older_than_the_declared_freshness_bound_abstains() -> None:
    """Прострочений доказ — не відмова провайдера, а відсутність підстави відповідати."""
    output = {"value": "ok"}
    spec = _evidence_spec(profile=EvidenceProfile.EXECUTION_ONLY, freshness_seconds=1)
    adapter = _FixedOutputAdapter(
        output, _envelope(output, observed_at=datetime(2026, 9, 5, 6, 45, tzinfo=UTC))
    )

    result, _, _ = _run(adapter, spec=spec)

    assert result.outcome is InvocationOutcome.ABSTAINED
    assert result.error_code == "EVIDENCE_STALE"


def test_fresh_evidence_of_the_same_shape_succeeds() -> None:
    """Негативний контроль: карається ВІК доказу, не його наявність."""
    output = {"value": "ok"}
    spec = _evidence_spec(profile=EvidenceProfile.EXECUTION_ONLY, freshness_seconds=3600)
    adapter = _FixedOutputAdapter(output, _envelope(output, observed_at=datetime.now(UTC)))

    result, _, _ = _run(adapter, spec=spec)

    assert result.outcome is InvocationOutcome.SUCCESS


@pytest.mark.parametrize("evidence", [object(), {"status": "VALID"}])
def test_an_evidence_object_of_the_wrong_type_is_an_internal_error(evidence: object) -> None:
    """`AdapterExecutionResult.evidence` анотований, але НЕ перевіряється в рантаймі."""
    spec = _evidence_spec(profile=EvidenceProfile.EXECUTION_ONLY)
    adapter = _FixedOutputAdapter({"value": "ok"}, evidence)

    result, _, _ = _run(adapter, spec=spec)

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "INTERNAL_ERROR"


def test_an_unserializable_evidence_envelope_does_not_escape_the_gateway() -> None:
    """Другі двері того самого класу: конверт ПРАВИЛЬНОГО типу, який не серіалізується.

    `model_construct` обходить валідацію, тож `model_dump` кидає
    PydanticSerializationError — підклас ValueError, якого іменована відмова не ловила.
    Виміряно 08.09.2026: до правки це виходило з шлюзу необробленим трейсбеком.
    """
    envelope = EvidenceEnvelope.model_construct(
        schema_version="korpus.evidence-envelope.v1",
        status=EvidenceStatus.VALID,
        binding=object(),
        provenance=object(),
        observed_at=datetime.now(UTC),
    )
    spec = _evidence_spec(profile=EvidenceProfile.EXECUTION_ONLY)

    result, _, audit = _run(_FixedOutputAdapter({"value": "ok"}, envelope), spec=spec)

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "INTERNAL_ERROR"
    assert result.audit_record_id is None
    assert audit.calls == 0


def test_undigestible_output_is_still_recorded_as_a_schema_fault() -> None:
    """Аудит мусить лишитись: виклик стався, адаптер відпрацював, відповідь непридатна."""
    result, _, audit = _run(_FixedOutputAdapter({"value": {1, 2}}))

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "OUTPUT_SCHEMA_INVALID"
    assert result.audit_record_id == "audit-adapter-boundary"
    assert audit.calls == 1
