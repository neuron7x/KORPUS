from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from korpus.application.capability_gateway.adapters import AdapterRegistry
from korpus.application.capability_gateway.contracts import payload_digest
from korpus.application.capability_gateway.errors import (
    CapabilityContractError,
    CapabilityNotFound,
    CapabilityRegistrationError,
)
from korpus.application.capability_gateway.evidence import (
    EvidenceBinding,
    EvidenceEnvelope,
    EvidenceProvenance,
    EvidenceStatus,
    ProvenanceKind,
    validate_evidence,
)
from korpus.application.capability_gateway.types import (
    AdapterSpec,
    ActorType,
    AuthorizationSpec,
    CapabilityLifecycle,
    CapabilitySpec,
    DataEgressClass,
    DataPolicySpec,
    EffectClass,
    EvidenceProfile,
    EvidenceSpec,
    IdempotencySpec,
    InvocationActor,
    InvocationContext,
    ProviderType,
    RetrySpec,
    TimeoutSpec,
)


class _Adapter:
    def execute(self, **kwargs: object) -> object:
        return kwargs


def _spec(profile: EvidenceProfile = EvidenceProfile.PROVIDER_PROVENANCE) -> CapabilitySpec:
    return CapabilitySpec(
        schema_version="korpus.capability-spec.v1",
        capability_id="reference.public.read",
        version="1.0.0",
        description="Read governed reference.",
        provider_type=ProviderType.HTTP,
        adapter=AdapterSpec(adapter_id="http.reference", adapter_version="1.0.0"),
        effect_class=EffectClass.READ_REMOTE,
        input_schema_id="urn:korpus:test:input:v1",
        output_schema_id="urn:korpus:test:output:v1",
        authorization=AuthorizationSpec(
            action="integration:reference:read",
            resource_mapper="reference_public_resource_v1",
        ),
        evidence=EvidenceSpec(profile=profile, freshness_seconds=300, bind_output_digest=True),
        timeouts=TimeoutSpec(total_ms=5_000),
        retry=RetrySpec(max_attempts=1),
        idempotency=IdempotencySpec(required=False),
        data_policy=DataPolicySpec(
            egress_class=DataEgressClass.PUBLIC_ONLY,
            max_request_bytes=16_384,
            max_response_bytes=1_048_576,
        ),
        lifecycle=CapabilityLifecycle.ENABLED,
    )


def _context(now: datetime) -> InvocationContext:
    return InvocationContext(
        schema_version="korpus.invocation-context.v1",
        invocation_id=uuid4(),
        actor=InvocationActor(actor_type=ActorType.USER, subject_id="reader"),
        request_time=now,
        service_release="0.9.7",
        policy_context_digest="sha256:" + "0" * 64,
    )


def _evidence(
    *,
    spec: CapabilitySpec,
    context: InvocationContext,
    output: object,
    observed_at: datetime,
    output_digest: str | None = None,
    kind: ProvenanceKind = ProvenanceKind.REMOTE_RESPONSE,
    source_refs: list[str] | None = None,
    signature_ref: str | None = None,
) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        schema_version="korpus.evidence-envelope.v1",
        status=EvidenceStatus.VALID,
        binding=EvidenceBinding(
            invocation_id=context.invocation_id,
            capability_id=spec.capability_id,
            capability_version=spec.version,
            adapter_id=spec.adapter.adapter_id,
            adapter_version=spec.adapter.adapter_version,
            output_digest=output_digest or payload_digest(output),
        ),
        provenance=EvidenceProvenance(
            kind=kind,
            source_refs=source_refs if source_refs is not None else ["provider:response:1"],
        ),
        observed_at=observed_at,
        signature_ref=signature_ref,
    )


def test_adapter_registry_resolves_exact_declared_implementation() -> None:
    registry = AdapterRegistry()
    adapter = _Adapter()
    registry.register("http.reference", "1.0.0", adapter)

    assert registry.resolve(_spec()) is adapter


def test_adapter_registry_refuses_missing_or_duplicate_version() -> None:
    registry = AdapterRegistry()
    registry.register("http.reference", "1.0.0", _Adapter())

    with pytest.raises(CapabilityRegistrationError):
        registry.register("http.reference", "1.0.0", _Adapter())
    spec = _spec().model_copy(
        update={"adapter": AdapterSpec(adapter_id="http.reference", adapter_version="2.0.0")}
    )
    with pytest.raises(CapabilityNotFound):
        registry.resolve(spec)


def test_required_evidence_cannot_be_missing() -> None:
    now = datetime.now(UTC)
    with pytest.raises(CapabilityContractError, match="evidence is missing"):
        validate_evidence(
            spec=_spec(),
            context=_context(now),
            output={"value": 1},
            evidence=None,
            evaluated_at=now,
        )


def test_evidence_output_digest_is_binding_not_provider_assertion() -> None:
    now = datetime.now(UTC)
    spec = _spec()
    context = _context(now)
    output = {"value": 1}
    evidence = _evidence(
        spec=spec,
        context=context,
        output=output,
        observed_at=now,
        output_digest="sha256:" + "f" * 64,
    )

    with pytest.raises(CapabilityContractError, match="output digest"):
        validate_evidence(
            spec=spec,
            context=context,
            output=output,
            evidence=evidence,
            evaluated_at=now,
        )


def test_stale_provider_evidence_fails_closed() -> None:
    now = datetime.now(UTC)
    spec = _spec()
    context = _context(now)
    output = {"value": 1}
    evidence = _evidence(
        spec=spec,
        context=context,
        output=output,
        observed_at=now - timedelta(seconds=301),
    )

    with pytest.raises(CapabilityContractError, match="stale"):
        validate_evidence(
            spec=spec,
            context=context,
            output=output,
            evidence=evidence,
            evaluated_at=now,
        )


def test_empty_evidence_source_reference_is_invalid_by_construction() -> None:
    with pytest.raises(ValueError):
        EvidenceProvenance(
            kind=ProvenanceKind.SOURCE_EVIDENCE,
            source_refs=[""],
        )


def test_empty_signature_reference_is_invalid_by_construction() -> None:
    now = datetime.now(UTC)
    spec = _spec(EvidenceProfile.SIGNED_RECEIPT)
    with pytest.raises(ValueError):
        _evidence(
            spec=spec,
            context=_context(now),
            output={"value": 1},
            observed_at=now,
            kind=ProvenanceKind.SIGNED_RECEIPT,
            signature_ref="",
        )


def test_signed_receipt_profile_requires_signed_provenance_and_signature() -> None:
    now = datetime.now(UTC)
    spec = _spec(EvidenceProfile.SIGNED_RECEIPT)
    context = _context(now)
    output = {"value": 1}
    evidence = _evidence(
        spec=spec,
        context=context,
        output=output,
        observed_at=now,
        kind=ProvenanceKind.SIGNED_RECEIPT,
        signature_ref=None,
    )

    with pytest.raises(CapabilityContractError, match="signature reference"):
        validate_evidence(
            spec=spec,
            context=context,
            output=output,
            evidence=evidence,
            evaluated_at=now,
        )


def test_none_profile_accepts_absence_of_evidence_only() -> None:
    now = datetime.now(UTC)
    validate_evidence(
        spec=_spec(EvidenceProfile.NONE),
        context=_context(now),
        output={"value": 1},
        evidence=None,
        evaluated_at=now,
    )
