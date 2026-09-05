from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from korpus.application.capability_gateway.contracts import payload_digest
from korpus.application.capability_gateway.errors import CapabilityContractError, CapabilityGatewayError
from korpus.application.capability_gateway.types import CapabilitySpec, EffectClass, IntegrationRequest
from korpus.domain.models import Identity


class EffectState(StrEnum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    FAILED_KNOWN_NO_EFFECT = "FAILED_KNOWN_NO_EFFECT"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECONCILED = "RECONCILED"


class ReconciliationDisposition(StrEnum):
    CONFIRMED_COMMITTED = "CONFIRMED_COMMITTED"
    CONFIRMED_NO_EFFECT = "CONFIRMED_NO_EFFECT"


class IdempotencyConflict(CapabilityGatewayError):
    reason = "idempotency_conflict"


class EffectAuthorizationRequired(PermissionError):
    reason = "explicit_effect_authorization_required"


class InvalidEffectTransition(CapabilityGatewayError):
    reason = "invalid_effect_transition"


class InvalidEffectReservation(CapabilityGatewayError):
    reason = "invalid_effect_reservation"


@dataclass(frozen=True, slots=True)
class EffectRecord:
    subject_id: str
    idempotency_key: str
    binding_digest: str
    invocation_id: str
    capability_id: str
    capability_version: str
    logical_resource: str
    input_digest: str
    state: EffectState
    provider_reference: str | None = None
    reconciliation_disposition: ReconciliationDisposition | None = None

    def __post_init__(self) -> None:
        if self.state is EffectState.RECONCILED:
            if self.reconciliation_disposition is None:
                raise ValueError("reconciled effect record requires a resolved disposition")
        elif self.reconciliation_disposition is not None:
            raise ValueError("reconciliation disposition is valid only for RECONCILED state")


@dataclass(frozen=True, slots=True)
class EffectReservation:
    record: EffectRecord
    created: bool


@dataclass(frozen=True, slots=True)
class EffectGuard:
    required: bool
    should_execute: bool
    binding_digest: str | None
    reservation: EffectReservation | None


class EffectLedger(Protocol):
    """Durable atomic idempotency ledger port.

    `reserve` must serialize on `(subject_id, idempotency_key)`: two concurrent callers
    in the same subject scope may not both observe `created=True`. Different subjects
    cannot reserve or block one another merely by choosing the same client key.
    """

    def reserve(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        binding_digest: str,
        invocation_id: str,
        capability_id: str,
        capability_version: str,
        logical_resource: str,
        input_digest: str,
    ) -> EffectReservation: ...

    def transition(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected: EffectState,
        target: EffectState,
        provider_reference: str | None = None,
    ) -> EffectRecord: ...


_EFFECTFUL = frozenset(
    {
        EffectClass.WRITE_REMOTE,
        EffectClass.TRANSACTIONAL_SIDE_EFFECT,
        EffectClass.PRIVILEGED_ADMIN,
    }
)

_ALLOWED_TRANSITIONS: dict[EffectState, frozenset[EffectState]] = {
    EffectState.PENDING: frozenset(
        {
            EffectState.COMMITTED,
            EffectState.FAILED_KNOWN_NO_EFFECT,
            EffectState.OUTCOME_UNKNOWN,
        }
    ),
    EffectState.OUTCOME_UNKNOWN: frozenset({EffectState.RECONCILED}),
    EffectState.COMMITTED: frozenset(),
    EffectState.FAILED_KNOWN_NO_EFFECT: frozenset(),
    EffectState.RECONCILED: frozenset(),
}


def effectful(spec: CapabilitySpec) -> bool:
    return spec.effect_class in _EFFECTFUL


def effect_binding_digest(
    *,
    identity: Identity,
    spec: CapabilitySpec,
    request: IntegrationRequest,
    logical_resource: str,
) -> str:
    if request.idempotency_key is None:
        raise CapabilityContractError("effect binding requires an idempotency key")
    return payload_digest(
        {
            "subject_id": identity.subject,
            "capability_id": spec.capability_id,
            "capability_version": spec.version,
            "logical_resource": logical_resource,
            "canonical_input_digest": payload_digest(request.input),
            "idempotency_key": request.idempotency_key,
        }
    )


def _record_binding(record: EffectRecord) -> tuple[str, ...]:
    return (
        record.subject_id,
        record.idempotency_key,
        record.binding_digest,
        record.invocation_id,
        record.capability_id,
        record.capability_version,
        record.logical_resource,
        record.input_digest,
    )


def attest_effect_transition(
    previous: EffectRecord,
    updated: object,
    *,
    target: EffectState,
    provider_reference: str | None = None,
) -> EffectRecord:
    """Require the durable transition result to prove the write that was requested."""

    if not isinstance(updated, EffectRecord):
        raise InvalidEffectTransition("effect ledger returned an invalid transition record type")
    if _record_binding(updated) != _record_binding(previous):
        raise InvalidEffectTransition("effect transition changed immutable reservation binding")
    if updated.state is not target:
        raise InvalidEffectTransition("effect transition did not persist the requested state")
    if updated.provider_reference != provider_reference:
        raise InvalidEffectTransition("effect transition provider reference does not match request")
    if updated.reconciliation_disposition is not None:
        raise InvalidEffectTransition("ordinary effect transition cannot set reconciliation disposition")
    return updated


def _attest_reservation(
    reservation: object,
    *,
    identity: Identity,
    spec: CapabilitySpec,
    request: IntegrationRequest,
    logical_resource: str,
    invocation_id: str,
    input_digest: str,
    binding_digest: str,
) -> EffectReservation:
    """Validate durable-ledger output before it can authorize dispatch semantics.

    The ledger is authoritative durable state, but a Python port return value is not trusted
    merely because its static type says `EffectReservation`. Exact field binding and the
    `created=True -> PENDING/current invocation` relation are required before execution.
    """

    if not isinstance(reservation, EffectReservation):
        raise InvalidEffectReservation("effect ledger returned an invalid reservation type")
    if not isinstance(reservation.created, bool):
        raise InvalidEffectReservation("effect reservation created flag is not boolean")
    record = reservation.record
    if not isinstance(record, EffectRecord):
        raise InvalidEffectReservation("effect ledger returned an invalid record type")
    if record.binding_digest != binding_digest:
        raise IdempotencyConflict(
            "idempotency key is already bound to a different capability/resource/input"
        )
    expected = (
        identity.subject,
        request.idempotency_key,
        binding_digest,
        spec.capability_id,
        spec.version,
        logical_resource,
        input_digest,
    )
    observed = (
        record.subject_id,
        record.idempotency_key,
        record.binding_digest,
        record.capability_id,
        record.capability_version,
        record.logical_resource,
        record.input_digest,
    )
    if observed != expected:
        raise InvalidEffectReservation("effect reservation exact binding fields are inconsistent")
    if not isinstance(record.state, EffectState):
        raise InvalidEffectReservation("effect reservation state is not canonical")
    if reservation.created:
        if record.state is not EffectState.PENDING:
            raise InvalidEffectReservation("new effect reservation is not PENDING")
        if record.invocation_id != invocation_id:
            raise InvalidEffectReservation("new effect reservation invocation binding is inconsistent")
        if record.provider_reference is not None or record.reconciliation_disposition is not None:
            raise InvalidEffectReservation("new effect reservation contains terminal provider state")
    return reservation


def prepare_effect_guard(
    *,
    identity: Identity,
    spec: CapabilitySpec,
    request: IntegrationRequest,
    logical_resource: str,
    invocation_id: str,
    ledger: EffectLedger,
    explicit_effect_authorized: bool,
) -> EffectGuard:
    required = effectful(spec) or spec.idempotency.required
    if not required:
        return EffectGuard(
            required=False,
            should_execute=True,
            binding_digest=None,
            reservation=None,
        )

    if effectful(spec) and not spec.idempotency.required:
        raise CapabilityContractError(
            "effectful capability must declare durable idempotency as required"
        )
    if (
        effectful(spec)
        and spec.authorization.requires_explicit_effect_authorization
        and not explicit_effect_authorized
    ):
        raise EffectAuthorizationRequired(
            "effectful capability requires a separate trusted authorization decision"
        )
    if request.idempotency_key is None:
        raise CapabilityContractError("effectful invocation requires an idempotency key")

    input_digest = payload_digest(request.input)
    binding = effect_binding_digest(
        identity=identity,
        spec=spec,
        request=request,
        logical_resource=logical_resource,
    )
    raw_reservation = ledger.reserve(
        subject_id=identity.subject,
        idempotency_key=request.idempotency_key,
        binding_digest=binding,
        invocation_id=invocation_id,
        capability_id=spec.capability_id,
        capability_version=spec.version,
        logical_resource=logical_resource,
        input_digest=input_digest,
    )
    reservation = _attest_reservation(
        raw_reservation,
        identity=identity,
        spec=spec,
        request=request,
        logical_resource=logical_resource,
        invocation_id=invocation_id,
        input_digest=input_digest,
        binding_digest=binding,
    )
    return EffectGuard(
        required=True,
        should_execute=reservation.created,
        binding_digest=binding,
        reservation=reservation,
    )


def assert_effect_transition(current: EffectState, target: EffectState) -> None:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidEffectTransition(f"forbidden effect transition: {current.value} -> {target.value}")
