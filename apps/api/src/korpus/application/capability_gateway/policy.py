from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from korpus.application.capability_gateway.errors import (
    CapabilityAuthorizationDenied,
    CapabilityPolicyIndeterminate,
)
from korpus.application.capability_gateway.types import CapabilitySpec
from korpus.application.policy import AuthorizationError, KNOWN_PERMISSIONS, PolicyEngine
from korpus.domain.models import Identity

ResourceAuthorizer = Callable[[Identity, CapabilitySpec, str], bool]


@dataclass(frozen=True, slots=True)
class CapabilityPolicyDecision:
    capability_id: str
    capability_version: str
    action: str
    canonical_permission: str
    allowed: bool
    reason: str


class CapabilityPolicyBridge:
    """Fail-closed bridge into canonical KORPUS action and resource policy.

    Capability actions are proposal-owned identifiers and never become KORPUS permissions
    implicitly. Action authority is mapped to the existing closed permission vocabulary.
    Resource authority is a separate server-owned predicate keyed by the registered resource
    mapper. Provider metadata, request claims and adapter credentials participate in neither.
    """

    def __init__(
        self,
        policy: PolicyEngine,
        *,
        action_permissions: Mapping[str, str],
        resource_authorizers: Mapping[str, ResourceAuthorizer] | None = None,
    ) -> None:
        normalized: dict[str, str] = {}
        for action, permission in action_permissions.items():
            action_name = action.strip()
            permission_name = permission.strip()
            if not action_name:
                raise ValueError("capability action mapping contains an empty action")
            if permission_name not in KNOWN_PERMISSIONS:
                raise ValueError(
                    f"unknown canonical permission in capability mapping: {permission_name}"
                )
            normalized[action_name] = permission_name

        normalized_resources: dict[str, ResourceAuthorizer] = {}
        for mapper_id, authorizer in (resource_authorizers or {}).items():
            key = mapper_id.strip()
            if not key:
                raise ValueError("resource authorizer mapping contains an empty mapper id")
            if not callable(authorizer):
                raise ValueError(f"resource authorizer is not callable: {key}")
            normalized_resources[key] = authorizer

        self._policy = policy
        self._action_permissions = normalized
        self._resource_authorizers = normalized_resources

    def has_action_mapping(self, spec: CapabilitySpec) -> bool:
        return spec.authorization.action in self._action_permissions

    def has_resource_authorizer(self, spec: CapabilitySpec) -> bool:
        return spec.authorization.resource_mapper in self._resource_authorizers

    def authorize(self, identity: Identity, spec: CapabilitySpec) -> CapabilityPolicyDecision:
        """Authorize only the canonical action permission.

        This method remains useful for composition/unit checks. Runtime capability execution
        must call `authorize_resource`, which adds the independent logical-resource predicate.
        """

        action = spec.authorization.action
        permission = self._action_permissions.get(action)
        if permission is None:
            raise CapabilityAuthorizationDenied(f"unmapped capability action: {action}")
        try:
            result = self._policy.require(identity, permission)
        except AuthorizationError as exc:
            raise CapabilityAuthorizationDenied(
                f"canonical policy denied {action} via {permission}: {exc}"
            ) from exc
        except Exception as exc:
            raise CapabilityPolicyIndeterminate("canonical policy could not decide") from exc
        if result is not None:
            raise CapabilityPolicyIndeterminate(
                "canonical policy returned a non-None authorization sentinel"
            )
        return CapabilityPolicyDecision(
            capability_id=spec.capability_id,
            capability_version=spec.version,
            action=action,
            canonical_permission=permission,
            allowed=True,
            reason="canonical_policy_allowed",
        )

    def _attest_action_decision(
        self,
        decision: object,
        spec: CapabilitySpec,
    ) -> CapabilityPolicyDecision:
        expected_permission = self._action_permissions.get(spec.authorization.action)
        if not isinstance(decision, CapabilityPolicyDecision) or expected_permission is None:
            raise CapabilityPolicyIndeterminate("canonical action decision is invalid")
        if decision.allowed is not True:
            raise CapabilityPolicyIndeterminate("canonical action decision is not an explicit allow")
        observed = (
            decision.capability_id,
            decision.capability_version,
            decision.action,
            decision.canonical_permission,
        )
        expected = (
            spec.capability_id,
            spec.version,
            spec.authorization.action,
            expected_permission,
        )
        if observed != expected:
            raise CapabilityPolicyIndeterminate("canonical action decision binding mismatch")
        return decision

    def authorize_resource(
        self,
        identity: Identity,
        spec: CapabilitySpec,
        *,
        logical_resource: str,
    ) -> CapabilityPolicyDecision:
        """Require both canonical action authority and exact resource authority."""

        action_decision = self._attest_action_decision(self.authorize(identity, spec), spec)
        resource = logical_resource.strip()
        if not resource:
            raise CapabilityPolicyIndeterminate("logical resource is empty")

        mapper_id = spec.authorization.resource_mapper
        authorizer = self._resource_authorizers.get(mapper_id)
        if authorizer is None:
            raise CapabilityPolicyIndeterminate(
                f"resource authorizer is not registered: {mapper_id}"
            )
        try:
            allowed = authorizer(identity, spec, resource)
        except Exception as exc:
            raise CapabilityPolicyIndeterminate(
                f"resource policy could not decide: {mapper_id}"
            ) from exc
        if allowed is False:
            raise CapabilityAuthorizationDenied(
                f"resource policy denied {spec.authorization.action} on {resource}"
            )
        if allowed is not True:
            raise CapabilityPolicyIndeterminate(
                f"resource policy returned a non-boolean decision: {mapper_id}"
            )

        return CapabilityPolicyDecision(
            capability_id=action_decision.capability_id,
            capability_version=action_decision.capability_version,
            action=action_decision.action,
            canonical_permission=action_decision.canonical_permission,
            allowed=True,
            reason="canonical_policy_and_resource_allowed",
        )
