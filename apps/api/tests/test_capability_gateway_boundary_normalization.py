from __future__ import annotations

from dataclasses import replace

from korpus.application.capability_gateway.adapters import AdapterExecutionResult, AdapterRegistry
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.effects import (
    EffectRecord,
    EffectReservation,
    EffectState,
    assert_effect_transition,
)
from korpus.application.capability_gateway.invoke import CapabilityGateway
from korpus.application.capability_gateway.policy import CapabilityPolicyBridge
from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.types import (
    AdapterSpec,
    AuthorizationSpec,
    CapabilityLifecycle,
    CapabilitySpec,
    DataEgressClass,
    DataPolicySpec,
    EffectClass,
    EvidenceProfile,
    EvidenceSpec,
    IdempotencySpec,
    IntegrationRequest,
    ProviderType,
    RetrySpec,
    TimeoutSpec,
)
from korpus.application.policy import PolicyEngine
from korpus.domain.models import Identity


class _Schemas:
    def validate(self, schema_id: str, value: object) -> None:
        del schema_id, value


class _Egress:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def check(self, **kwargs: object) -> None:
        del kwargs
        if self.error is not None:
            raise self.error


class _EffectAuthorizer:
    def __init__(self, *, allowed: bool = True, error: Exception | None = None) -> None:
        self.allowed = allowed
        self.error = error

    def authorize(self, **kwargs: object) -> bool:
        del kwargs
        if self.error is not None:
            raise self.error
        return self.allowed


class _Ledger:
    def __init__(self, reserve_error: Exception | None = None) -> None:
        self.reserve_error = reserve_error
        self.records: dict[tuple[str, str], EffectRecord] = {}

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
    ) -> EffectReservation:
        if self.reserve_error is not None:
            raise self.reserve_error
        key = subject_id, idempotency_key
        existing = self.records.get(key)
        if existing is not None:
            return EffectReservation(record=existing, created=False)
        record = EffectRecord(
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            binding_digest=binding_digest,
            invocation_id=invocation_id,
            capability_id=capability_id,
            capability_version=capability_version,
            logical_resource=logical_resource,
            input_digest=input_digest,
            state=EffectState.PENDING,
        )
        self.records[key] = record
        return EffectReservation(record=record, created=True)

    def transition(
        self,
        *,
        subject_id: str,
        idempotency_key: str,
        expected: EffectState,
        target: EffectState,
        provider_reference: str | None = None,
    ) -> EffectRecord:
        key = subject_id, idempotency_key
        current = self.records[key]
        assert current.state is expected
        assert_effect_transition(current.state, target)
        updated = replace(current, state=target, provider_reference=provider_reference)
        self.records[key] = updated
        return updated


class _Audit:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def append(self, **kwargs: object) -> str:
        del kwargs
        self.calls += 1
        if self.error is not None:
            raise self.error
        return "audit-boundary-1"


class _Adapter:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def execute(self, **kwargs: object) -> AdapterExecutionResult:
        del kwargs
        self.calls += 1
        if self.error is not None:
            raise self.error
        return AdapterExecutionResult(output={"value": "ok"})


def _spec(*, effect: EffectClass = EffectClass.READ_LOCAL) -> CapabilitySpec:
    effectful = effect in {
        EffectClass.WRITE_REMOTE,
        EffectClass.TRANSACTIONAL_SIDE_EFFECT,
        EffectClass.PRIVILEGED_ADMIN,
    }
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.boundary.action",
        version="1.0.0",
        description="Boundary-normalization test capability.",
        provider_type=ProviderType.INTERNAL,
        adapter=AdapterSpec(adapter_id="internal.boundary", adapter_version="1.0.0"),
        effect_class=effect,
        input_schema_id="urn:korpus:test:boundary-input:v1",
        output_schema_id="urn:korpus:test:boundary-output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:boundary",
            resource_mapper="boundary_resource_v1",
            requires_explicit_effect_authorization=effectful,
        ),
        evidence=EvidenceSpec(profile=EvidenceProfile.NONE),
        timeouts=TimeoutSpec(total_ms=1000),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=effectful),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.NONE,
            max_request_bytes=4096,
            max_response_bytes=4096,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _request(*, input_value: dict[str, object] | None = None, key: str | None = None) -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.boundary.action",
        capability_version="1.0.0",
        input=input_value if input_value is not None else {"reference_id": "1"},
        idempotency_key=key,
    )


def _gateway(
    *,
    effect: EffectClass = EffectClass.READ_LOCAL,
    mapper: object | None = None,
    egress: _Egress | None = None,
    authorizer: _EffectAuthorizer | None = None,
    ledger: _Ledger | None = None,
    audit: _Audit | None = None,
    adapter: _Adapter | None = None,
) -> tuple[CapabilityGateway, _Adapter, _Ledger, _Audit]:
    selected_adapter = adapter or _Adapter()
    selected_ledger = ledger or _Ledger()
    selected_audit = audit or _Audit()
    adapters = AdapterRegistry()
    adapters.register("internal.boundary", "1.0.0", selected_adapter)
    resource_mapper = mapper or (
        lambda identity, spec, request: f"reference:{request.input['reference_id']}"
    )
    gateway = CapabilityGateway(
        registry=CapabilityRegistry([_spec(effect=effect)]),
        policy=CapabilityPolicyBridge(
            PolicyEngine(),
            action_permissions={"integration:reference:boundary": "answer:read"},
            resource_authorizers={"boundary_resource_v1": lambda identity, spec, resource: True},
        ),
        adapters=adapters,
        schemas=_Schemas(),
        resource_mappers={"boundary_resource_v1": resource_mapper},  # type: ignore[dict-item]
        egress=egress or _Egress(),
        effect_authorizer=authorizer or _EffectAuthorizer(),
        effects=selected_ledger,
        audit=selected_audit,
    )
    return gateway, selected_adapter, selected_ledger, selected_audit


def _identity() -> Identity:
    return Identity(subject="reader", roles=frozenset({"user"}))


def test_mapper_key_error_is_normalized_to_invalid_input_without_execution() -> None:
    gateway, adapter, _, audit = _gateway()

    result = gateway.invoke(identity=_identity(), request=_request(input_value={}))

    assert result.outcome is InvocationOutcome.REJECTED
    assert result.error_code == "INPUT_SCHEMA_INVALID"
    assert adapter.calls == 0
    assert audit.calls == 0


def test_unexpected_mapper_failure_is_stable_fail_closed() -> None:
    def fail_mapper(*args: object) -> str:
        del args
        raise OSError("mapper backend exploded")

    gateway, adapter, _, _ = _gateway(mapper=fail_mapper)

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "RESOURCE_MAPPING_FAILED"
    assert adapter.calls == 0


def test_non_runtime_egress_failure_cannot_reach_adapter() -> None:
    gateway, adapter, _, audit = _gateway(egress=_Egress(ValueError("classifier failed")))

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "EGRESS_POLICY_FAILED"
    assert adapter.calls == 0
    assert audit.calls == 1


def test_non_runtime_effect_authorizer_failure_denies_before_reservation() -> None:
    ledger = _Ledger()
    gateway, adapter, _, _ = _gateway(
        effect=EffectClass.WRITE_REMOTE,
        authorizer=_EffectAuthorizer(error=OSError("authorization backend unavailable")),
        ledger=ledger,
    )

    result = gateway.invoke(identity=_identity(), request=_request(key="idem-1"))

    assert result.outcome is InvocationOutcome.DENIED
    assert result.error_code == "EFFECT_AUTH_REQUIRED"
    assert ledger.records == {}
    assert adapter.calls == 0


def test_non_runtime_effect_ledger_failure_is_stable_fail_closed() -> None:
    ledger = _Ledger(reserve_error=OSError("ledger unavailable"))
    gateway, adapter, _, audit = _gateway(effect=EffectClass.WRITE_REMOTE, ledger=ledger)

    result = gateway.invoke(identity=_identity(), request=_request(key="idem-1"))

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "INTERNAL_ERROR"
    assert adapter.calls == 0
    assert audit.calls == 1


def test_non_runtime_read_adapter_failure_is_stable_failed() -> None:
    gateway, adapter, _, audit = _gateway(adapter=_Adapter(OSError("unexpected adapter fault")))

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "INTERNAL_ERROR"
    assert adapter.calls == 1
    assert audit.calls == 1


def test_non_runtime_effect_adapter_failure_is_outcome_unknown() -> None:
    ledger = _Ledger()
    gateway, adapter, _, audit = _gateway(
        effect=EffectClass.WRITE_REMOTE,
        adapter=_Adapter(OSError("unexpected adapter fault")),
        ledger=ledger,
    )

    result = gateway.invoke(identity=_identity(), request=_request(key="idem-1"))

    assert result.outcome is InvocationOutcome.OUTCOME_UNKNOWN
    assert result.error_code == "INTERNAL_ERROR"
    assert adapter.calls == 1
    assert ledger.records[("reader", "idem-1")].state is EffectState.OUTCOME_UNKNOWN
    assert audit.calls == 1


def test_non_runtime_audit_failure_never_returns_success() -> None:
    gateway, adapter, _, audit = _gateway(audit=_Audit(OSError("audit store unavailable")))

    result = gateway.invoke(identity=_identity(), request=_request())

    assert adapter.calls == 1
    assert audit.calls == 1
    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "AUDIT_APPEND_FAILED"
    assert result.output is None
