from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from korpus.application.capability_gateway.effect_safety import (
    EffectSafetyRegistry,
    ReconciliationMode,
)
from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectState,
    ReconciliationDisposition,
)
from korpus.application.capability_gateway.errors import (
    CapabilityAuthorizationDenied,
    CapabilityGatewayError,
    CapabilityRegistrationError,
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
    """Server-composed, provider-specific read-only reconciliation strategy.

    `reconciliation_mode` is local composition metadata. Provider descriptions, annotations
    and response bodies cannot select or widen the strategy used for an effectful capability.
    Implementations may query provider state but must never dispatch the original effect again.
    """

    reconciliation_mode: ReconciliationMode

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
    effect_safety: EffectSafetyRegistry,
) -> EffectRecord:
    """Resolve one OUTCOME_UNKNOWN record without re-dispatching the original effect.

    Authorization is supplied by the canonical policy/effect authority outside this helper.
    Only the literal boolean `True` is admitted; request/provider metadata cannot widen it.
    The exact-bound deployment safety declaration selects the admissible reconciliation
    strategy, and the durable ledger performs the final compare-and-set on state + binding.

    This helper is intentionally an automatic provider-observation path. A capability whose
    exact safety declaration says `MANUAL` is refused here and must use a distinct authorized,
    audited operator workflow rather than smuggling a manual decision through a resolver.
    """

    if authorized is not True:
        raise CapabilityAuthorizationDenied("effect reconciliation authorization denied")
    if not idempotency_key or not idempotency_key.strip():
        raise ReconciliationConflict("reconciliation requires a non-blank idempotency key")
    if not expected_binding_digest:
        raise ReconciliationConflict("reconciliation requires an exact effect binding digest")

    try:
        record = ledger.get(subject_id=identity.subject, idempotency_key=idempotency_key)
    except Exception as exc:
        raise ReconciliationIndeterminate("durable reconciliation state is unavailable") from exc
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
        safety = effect_safety.resolve_exact(spec)
    except CapabilityRegistrationError as exc:
        raise ReconciliationConflict(
            "exact effect safety declaration is unavailable or drifted"
        ) from exc
    except Exception as exc:
        raise ReconciliationConflict(
            "exact effect safety declaration could not be evaluated"
        ) from exc

    declared_mode = safety.reconciliation_mode
    if declared_mode is ReconciliationMode.MANUAL:
        raise ReconciliationIndeterminate("manual reconciliation is required by effect safety")

    try:
        resolver_mode = getattr(resolver, "reconciliation_mode", None)
    except Exception as exc:
        raise ReconciliationConflict("reconciliation resolver mode could not be evaluated") from exc
    if not isinstance(resolver_mode, ReconciliationMode):
        raise ReconciliationConflict("reconciliation resolver mode is invalid")
    if resolver_mode is not declared_mode:
        raise ReconciliationConflict(
            "reconciliation resolver mode does not match exact effect safety declaration"
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
