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


class IdempotencyConflict(CapabilityGatewayError):
    reason = "idempotency_conflict"


class EffectAuthorizationRequired(PermissionError):
    reason = "explicit_effect_authorization_required"


class InvalidEffectTransition(CapabilityGatewayError):
    reason = "invalid_effect_transition"


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
    reservation = ledger.reserve(
        subject_id=identity.subject,
        idempotency_key=request.idempotency_key,
        binding_digest=binding,
        invocation_id=invocation_id,
        capability_id=spec.capability_id,
        capability_version=spec.version,
        logical_resource=logical_resource,
        input_digest=input_digest,
    )
    if reservation.record.binding_digest != binding:
        raise IdempotencyConflict(
            "idempotency key is already bound to a different capability/resource/input"
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
