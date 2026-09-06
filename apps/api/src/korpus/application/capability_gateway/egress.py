from __future__ import annotations

from typing import Protocol

from korpus.application.capability_gateway.types import (
    CapabilitySpec,
    DataEgressClass,
    IntegrationRequest,
    ProviderType,
)
from korpus.domain.models import AccessTier, Identity


class CapabilityEgressDenied(PermissionError):
    reason = "capability_egress_denied"


class RequestClassificationResolver(Protocol):
    """Returns the highest trusted classification carried by this invocation payload."""

    def classify_request(
        self,
        *,
        identity: Identity,
        spec: CapabilitySpec,
        request: IntegrationRequest,
        logical_resource: str,
    ) -> AccessTier: ...


class ExternalDataPolicy(Protocol):
    """Deployment-owned decision for POLICY_GATED external data transfer."""

    def permits(
        self,
        *,
        identity: Identity,
        spec: CapabilitySpec,
        max_tier: AccessTier,
        logical_resource: str,
    ) -> bool: ...


_REMOTE_PROVIDERS = frozenset(
    {
        ProviderType.HTTP,
        ProviderType.MCP,
        ProviderType.QUEUE,
        ProviderType.OBJECT_STORE,
        ProviderType.CUSTOM,
    }
)


class CapabilityDataEgressGuard:
    """Separates action authorization from permission to export invocation data.

    Provider credentials and provider-side scopes are intentionally absent. The decision
    uses a server-owned capability declaration plus trusted request classification and a
    deployment-owned external-data policy.
    """

    def __init__(
        self,
        classification: RequestClassificationResolver,
        external_policy: ExternalDataPolicy,
    ) -> None:
        self._classification = classification
        self._external_policy = external_policy

    def check(
        self,
        *,
        identity: Identity,
        spec: CapabilitySpec,
        request: IntegrationRequest,
        logical_resource: str,
    ) -> None:
        if spec.provider_type not in _REMOTE_PROVIDERS:
            return

        egress_class = spec.data_policy.egress_class
        if egress_class in {DataEgressClass.NONE, DataEgressClass.RESTRICTED_NO_EGRESS}:
            raise CapabilityEgressDenied(
                f"{spec.capability_id}@{spec.version} does not permit external data egress"
            )

        max_tier = self._classification.classify_request(
            identity=identity,
            spec=spec,
            request=request,
            logical_resource=logical_resource,
        )
        if not isinstance(max_tier, AccessTier):
            raise RuntimeError("request classification resolver returned an invalid tier")

        if egress_class is DataEgressClass.PUBLIC_ONLY:
            if max_tier > AccessTier.PUBLIC:
                raise CapabilityEgressDenied(
                    f"PUBLIC_ONLY capability cannot export {max_tier.label()} material"
                )
            return

        if egress_class is not DataEgressClass.POLICY_GATED:
            raise RuntimeError(f"unsupported egress class: {egress_class.value}")
        permitted = self._external_policy.permits(
            identity=identity,
            spec=spec,
            max_tier=max_tier,
            logical_resource=logical_resource,
        )
        if permitted is False:
            raise CapabilityEgressDenied("deployment external-data policy denied capability egress")
        if permitted is not True:
            raise RuntimeError("deployment external-data policy returned a non-boolean decision")
