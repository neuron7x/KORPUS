from __future__ import annotations

from collections.abc import Callable, Mapping

from korpus.application.capability_gateway.adapters import (
    AdapterExecutionFailed,
    AdapterExecutionResult,
)
from korpus.application.capability_gateway.contracts import payload_digest
from korpus.application.capability_gateway.evidence import (
    EvidenceBinding,
    EvidenceEnvelope,
    EvidenceProvenance,
    EvidenceStatus,
    ProvenanceKind,
)
from korpus.application.capability_gateway.types import (
    CapabilitySpec,
    EffectClass,
    EvidenceProfile,
    IntegrationRequest,
    InvocationContext,
    ProviderType,
)

InternalHandler = Callable[[Mapping[str, object], str], object]


class InternalFunctionAdapter:
    """No-network adapter for server-owned deterministic read functions.

    It is intentionally narrow: only INTERNAL/READ_LOCAL capabilities with NONE or
    EXECUTION_ONLY evidence are admitted. The handler receives validated request data
    and a server-derived logical resource; it receives no credentials and owns no
    authorization decision.
    """

    def __init__(self, handler: InternalHandler) -> None:
        self._handler = handler

    def execute(
        self,
        *,
        spec: CapabilitySpec,
        request: IntegrationRequest,
        context: InvocationContext,
        logical_resource: str,
    ) -> AdapterExecutionResult:
        if spec.provider_type is not ProviderType.INTERNAL:
            raise AdapterExecutionFailed("internal adapter cannot execute a remote provider")
        if spec.effect_class is not EffectClass.READ_LOCAL:
            raise AdapterExecutionFailed("internal adapter is read-only")
        if spec.evidence.profile not in {EvidenceProfile.NONE, EvidenceProfile.EXECUTION_ONLY}:
            raise AdapterExecutionFailed(
                "internal adapter cannot manufacture provider, factual, or signed evidence"
            )

        try:
            output = self._handler(request.input, logical_resource)
            output_digest = payload_digest(output)
        except (TypeError, ValueError, RuntimeError) as exc:
            raise AdapterExecutionFailed("internal handler failed") from exc

        evidence: EvidenceEnvelope | None = None
        if spec.evidence.profile is EvidenceProfile.EXECUTION_ONLY:
            evidence = EvidenceEnvelope(
                schema_version="korpus.evidence-envelope.v1",
                status=EvidenceStatus.VALID,
                binding=EvidenceBinding(
                    invocation_id=context.invocation_id,
                    capability_id=spec.capability_id,
                    capability_version=spec.version,
                    adapter_id=spec.adapter.adapter_id,
                    adapter_version=spec.adapter.adapter_version,
                    output_digest=output_digest,
                ),
                provenance=EvidenceProvenance(
                    kind=ProvenanceKind.INTERNAL,
                    source_refs=[f"internal:{logical_resource}"],
                ),
                observed_at=context.request_time,
                reproducible=True,
            )

        return AdapterExecutionResult(output=output, evidence=evidence)
