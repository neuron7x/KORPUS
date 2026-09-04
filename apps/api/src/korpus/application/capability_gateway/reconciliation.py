from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectState,
    ReconciliationDisposition,
)
from korpus.application.capability_gateway.errors import (
    CapabilityAuthorizationDenied,
    CapabilityGatewayError,
)
from korpus.application.capability_gateway.types import CapabilitySpec
from korpus.domain.models import Identity

_MAX_PROVIDER_REFERENCE_LENGTH = 512


class ReconciliationConflict(CapabilityGatewayError):
    reason = "effect_reconciliation_conflict"


class ReconciliationIndeterminate(CapabilityGatewayError):
    reason = "effect_reconciliation_indeterminate"


@dataclass(frozen=True, slots=True)
class ReconciliationObservation:
    """Provider-specific read-only observation of an ambiguous external effect."""

    disposition: ReconciliationDisposition
    provider_reference: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ReconciliationDisposition):
            raise ValueError("reconciliation disposition must be a registered enum value")
        if self.provider_reference is None:
            return
        if not isinstance(self.provider_reference, str) or not self.provider_reference.strip():
            raise ValueError("reconciliation provider reference must be a non-blank string")
        if len(self.provider_reference) > _MAX_PROVIDER_REFERENCE_LENGTH:
            raise ValueError("reconciliation provider reference exceeds maximum length")


class EffectOutcomeResolver(Protocol):
    """Provider-specific status resolver.

    Implementations may query provider state but must not dispatch the original effect again.
    """

    def observe(
        self,
        *,
        spec: CapabilitySpec,
        record: EffectRecord,
    ) -> ReconciliationObservation: ...


class ReconciliationLedger(Protocol):
    def get(self, *, subject_id: str, idempotency_key: str) -> EffectRecord | None: ...

    def reconcile(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected_binding_digest: str,
        disposition: ReconciliationDisposition,
        provider_reference: str | None = None,
    ) -> EffectRecord: ...


def reconcile_unknown_effect(
    *,
    identity: Identity,
    spec: CapabilitySpec,
    idempotency_key: str,
    expected_binding_digest: str,
    authorized: bool,
    ledger: ReconciliationLedger,
    resolver: EffectOutcomeResolver,
) -> EffectRecord:
    """Resolve one OUTCOME_UNKNOWN record without re-dispatching the original effect.

    Authorization is supplied by the canonical policy/effect authority outside this helper.
    Only the literal boolean `True` is admitted; request/provider metadata cannot widen it.
    The durable ledger performs the final compare-and-set on state + exact binding.
    """

    if authorized is not True:
        raise CapabilityAuthorizationDenied("effect reconciliation authorization denied")
    if not idempotency_key or not idempotency_key.strip():
        raise ReconciliationConflict("reconciliation requires a non-blank idempotency key")
    if not expected_binding_digest:
        raise ReconciliationConflict("reconciliation requires an exact effect binding digest")

    record = ledger.get(subject_id=identity.subject, idempotency_key=idempotency_key)
    if record is None:
        raise ReconciliationConflict("effect reservation does not exist")
    if record.subject_id != identity.subject:
        raise ReconciliationConflict("effect subject binding mismatch")
    if (record.capability_id, record.capability_version) != (spec.capability_id, spec.version):
        raise ReconciliationConflict("effect capability binding mismatch")
    if record.binding_digest != expected_binding_digest:
        raise ReconciliationConflict("effect idempotency binding mismatch")
    if record.state is not EffectState.OUTCOME_UNKNOWN:
        raise ReconciliationConflict(
            f"effect is not reconcilable from state {record.state.value}"
        )

    try:
        observation = resolver.observe(spec=spec, record=record)
    except ReconciliationIndeterminate:
        raise
    except Exception as exc:
        raise ReconciliationIndeterminate("provider reconciliation could not decide") from exc
    if not isinstance(observation, ReconciliationObservation):
        raise ReconciliationIndeterminate("provider reconciliation returned an invalid observation")

    if (
        record.provider_reference is not None
        and observation.provider_reference is not None
        and record.provider_reference != observation.provider_reference
    ):
        raise ReconciliationConflict("provider reference changed during reconciliation")
    provider_reference = observation.provider_reference or record.provider_reference

    try:
        return ledger.reconcile(
            subject_id=identity.subject,
            idempotency_key=idempotency_key,
            expected_binding_digest=expected_binding_digest,
            disposition=observation.disposition,
            provider_reference=provider_reference,
        )
    except ReconciliationConflict:
        raise
    except Exception as exc:
        raise ReconciliationConflict("durable reconciliation compare-and-set failed") from exc
