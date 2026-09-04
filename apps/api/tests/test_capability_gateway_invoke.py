from __future__ import annotations

from dataclasses import replace

from korpus.application.capability_gateway.adapters import (
    AdapterExecutionResult,
    AdapterOutcomeUnknown,
    AdapterRegistry,
)
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
    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.failing = failing

    def validate(self, schema_id: str, value: object) -> None:
        del value
        if schema_id in self.failing:
            raise ValueError(f"invalid against {schema_id}")


class _Egress:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def check(self, **kwargs: object) -> None:
        del kwargs
        if not self.allowed:
            raise PermissionError("blocked")


class _EffectAuthorizer:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def authorize(self, **kwargs: object) -> bool:
        del kwargs
        return self.allowed


class _Ledger:
    def __init__(self) -> None:
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
        if current.state is not expected:
            raise RuntimeError("compare-and-set failed")
        assert_effect_transition(current.state, target)
        updated = replace(current, state=target, provider_reference=provider_reference)
        self.records[key] = updated
        return updated


class _Audit:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def append(self, **kwargs: object) -> str:
        self.calls.append(dict(kwargs))
        if self.fail:
            raise RuntimeError("audit unavailable")
        return "audit-1"


class _Adapter:
    def __init__(
        self,
        result: AdapterExecutionResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or AdapterExecutionResult(output={"value": "ok"})
        self.error = error
        self.calls = 0

    def execute(self, **kwargs: object) -> AdapterExecutionResult:
        del kwargs
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _spec(
    *,
    effect: EffectClass = EffectClass.READ_LOCAL,
    evidence_profile: EvidenceProfile = EvidenceProfile.NONE,
) -> CapabilitySpec:
    effectful = effect in {
        EffectClass.WRITE_REMOTE,
        EffectClass.TRANSACTIONAL_SIDE_EFFECT,
        EffectClass.PRIVILEGED_ADMIN,
    }
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.public.action",
        version="1.0.0",
        description="Governed test capability.",
        provider_type=ProviderType.INTERNAL,
        adapter=AdapterSpec(adapter_id="internal.reference", adapter_version="1.0.0"),
        effect_class=effect,
        input_schema_id="urn:korpus:test:input:v1",
        output_schema_id="urn:korpus:test:output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:action",
            resource_mapper="reference_resource_v1",
            requires_explicit_effect_authorization=effectful,
        ),
        evidence=EvidenceSpec(profile=evidence_profile),
        timeouts=TimeoutSpec(total_ms=1_000),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=effectful),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.NONE,
            max_request_bytes=16_384,
            max_response_bytes=1_048_576,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _request(*, idempotency_key: str | None = None, dry_run: bool = False) -> IntegrationRequest:
    return IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.public.action",
        capability_version="1.0.0",
        input={"reference_id": "1"},
        idempotency_key=idempotency_key,
        dry_run=dry_run,
    )


def _gateway(
    *,
    spec: CapabilitySpec | None = None,
    adapter: _Adapter | None = None,
    schemas: _Schemas | None = None,
    egress: _Egress | None = None,
    effect_authorizer: _EffectAuthorizer | None = None,
    ledger: _Ledger | None = None,
    audit: _Audit | None = None,
    resource_allowed: bool = True,
    include_resource_authorizer: bool = True,
) -> tuple[CapabilityGateway, _Adapter, _Ledger, _Audit]:
    declared = spec or _spec()
    selected_adapter = adapter or _Adapter()
    selected_ledger = ledger or _Ledger()
    selected_audit = audit or _Audit()
    adapters = AdapterRegistry()
    adapters.register("internal.reference", "1.0.0", selected_adapter)
    gateway = CapabilityGateway(
        registry=CapabilityRegistry([declared]),
        policy=CapabilityPolicyBridge(
            PolicyEngine(),
            action_permissions={"integration:reference:action": "answer:read"},
            resource_authorizers=(
                {
                    "reference_resource_v1": (
                        lambda identity, capability, resource: resource_allowed
                    )
                }
                if include_resource_authorizer
                else {}
            ),
        ),
        adapters=adapters,
        schemas=schemas or _Schemas(),
        resource_mappers={
            "reference_resource_v1": lambda identity, capability, request: (
                f"reference:{request.input['reference_id']}"
            )
        },
        egress=egress or _Egress(),  # type: ignore[arg-type]
        effect_authorizer=effect_authorizer or _EffectAuthorizer(),  # type: ignore[arg-type]
        effects=selected_ledger,
        audit=selected_audit,  # type: ignore[arg-type]
    )
    return gateway, selected_adapter, selected_ledger, selected_audit


def _identity(*, roles: frozenset[str] = frozenset({"user"})) -> Identity:
    return Identity(subject="reader", roles=roles)


def test_unknown_capability_is_denied_before_any_adapter_call() -> None:
    gateway, adapter, _, _ = _gateway()
    request = _request().model_copy(update={"capability_version": "2.0.0"})

    result = gateway.invoke(identity=_identity(), request=request)

    assert result.outcome is InvocationOutcome.DENIED
    assert result.error_code == "CAPABILITY_UNKNOWN"
    assert adapter.calls == 0


def test_canonical_policy_denial_happens_before_adapter() -> None:
    gateway, adapter, _, _ = _gateway()

    result = gateway.invoke(identity=_identity(roles=frozenset()), request=_request())

    assert result.outcome is InvocationOutcome.DENIED
    assert result.error_code == "POLICY_DENIED"
    assert adapter.calls == 0


def test_resource_policy_denial_happens_before_adapter() -> None:
    gateway, adapter, _, _ = _gateway(resource_allowed=False)

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.DENIED
    assert result.error_code == "POLICY_DENIED"
    assert adapter.calls == 0


def test_missing_resource_policy_fails_closed_before_adapter() -> None:
    gateway, adapter, _, _ = _gateway(include_resource_authorizer=False)

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "POLICY_UNKNOWN"
    assert adapter.calls == 0


def test_read_only_success_returns_output_only_after_audit() -> None:
    gateway, adapter, _, audit = _gateway()

    result = gateway.invoke(identity=_identity(), request=_request())

    assert adapter.calls == 1
    assert result.outcome is InvocationOutcome.SUCCESS
    assert result.output == {"value": "ok"}
    assert result.audit_record_id == "audit-1"
    assert len(audit.calls) == 1


def test_output_schema_failure_never_exposes_provider_output() -> None:
    gateway, _, _, _ = _gateway(schemas=_Schemas(frozenset({"urn:korpus:test:output:v1"})))

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "OUTPUT_SCHEMA_INVALID"
    assert result.output is None
    assert result.evidence is None


def test_missing_required_evidence_abstains_without_exposing_output() -> None:
    gateway, _, _, _ = _gateway(spec=_spec(evidence_profile=EvidenceProfile.FACTUAL_EVIDENCE))

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.ABSTAINED
    assert result.error_code == "EVIDENCE_MISSING"
    assert result.output is None


def test_audit_failure_converts_success_to_fail_closed() -> None:
    gateway, _, _, _ = _gateway(audit=_Audit(fail=True))

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "AUDIT_APPEND_FAILED"
    assert result.output is None


def test_dry_run_is_rejected_until_semantics_are_explicit() -> None:
    gateway, adapter, _, _ = _gateway()

    result = gateway.invoke(identity=_identity(), request=_request(dry_run=True))

    assert result.outcome is InvocationOutcome.REJECTED
    assert result.error_code == "DRY_RUN_NOT_ADMITTED"
    assert adapter.calls == 0


def test_egress_denial_happens_before_adapter() -> None:
    gateway, adapter, _, _ = _gateway(egress=_Egress(allowed=False))

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.DENIED
    assert result.error_code == "EGRESS_DENIED"
    assert adapter.calls == 0


def test_effect_authorization_denial_happens_before_reservation_and_adapter() -> None:
    ledger = _Ledger()
    gateway, adapter, _, _ = _gateway(
        spec=_spec(effect=EffectClass.WRITE_REMOTE),
        effect_authorizer=_EffectAuthorizer(allowed=False),
        ledger=ledger,
    )

    result = gateway.invoke(identity=_identity(), request=_request(idempotency_key="idem-1"))

    assert result.outcome is InvocationOutcome.DENIED
    assert result.error_code == "EFFECT_AUTH_REQUIRED"
    assert ledger.records == {}
    assert adapter.calls == 0


def test_effectful_timeout_becomes_outcome_unknown_not_retry() -> None:
    ledger = _Ledger()
    adapter = _Adapter(error=AdapterOutcomeUnknown("transport timeout after dispatch"))
    gateway, selected_adapter, _, _ = _gateway(
        spec=_spec(effect=EffectClass.WRITE_REMOTE),
        adapter=adapter,
        ledger=ledger,
    )

    result = gateway.invoke(identity=_identity(), request=_request(idempotency_key="idem-1"))

    assert selected_adapter.calls == 1
    assert result.outcome is InvocationOutcome.OUTCOME_UNKNOWN
    assert result.error_code == "ADAPTER_TIMEOUT"
    assert ledger.records[("reader", "idem-1")].state is EffectState.OUTCOME_UNKNOWN


def test_effectful_success_commits_ledger_once() -> None:
    ledger = _Ledger()
    gateway, adapter, _, _ = _gateway(
        spec=_spec(effect=EffectClass.WRITE_REMOTE),
        ledger=ledger,
    )

    result = gateway.invoke(identity=_identity(), request=_request(idempotency_key="idem-1"))

    assert result.outcome is InvocationOutcome.SUCCESS
    assert adapter.calls == 1
    assert ledger.records[("reader", "idem-1")].state is EffectState.COMMITTED
