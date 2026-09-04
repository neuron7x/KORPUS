from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from korpus.application.capability_gateway.errors import CapabilityAuthorizationDenied
from korpus.application.capability_gateway.types import CapabilitySpec
from korpus.application.policy import AuthorizationError, KNOWN_PERMISSIONS, PolicyEngine
from korpus.domain.models import Identity


@dataclass(frozen=True, slots=True)
class CapabilityPolicyDecision:
    capability_id: str
    capability_version: str
    action: str
    canonical_permission: str
    allowed: bool
    reason: str


class CapabilityPolicyBridge:
    """Fail-closed bridge into the canonical KORPUS policy engine.

    Capability actions are proposal-owned identifiers and are not automatically KORPUS
    permissions. The server must provide an explicit action -> existing canonical
    permission mapping. Missing mappings deny; invalid mappings fail composition early.
    """

    def __init__(
        self,
        policy: PolicyEngine,
        *,
        action_permissions: Mapping[str, str],
    ) -> None:
        normalized: dict[str, str] = {}
        for action, permission in action_permissions.items():
            action_name = action.strip()
            permission_name = permission.strip()
            if not action_name:
                raise ValueError("capability action mapping contains an empty action")
            if permission_name not in KNOWN_PERMISSIONS:
                raise ValueError(f"unknown canonical permission in capability mapping: {permission_name}")
            normalized[action_name] = permission_name
        self._policy = policy
        self._action_permissions = normalized

    def authorize(self, identity: Identity, spec: CapabilitySpec) -> CapabilityPolicyDecision:
        action = spec.authorization.action
        permission = self._action_permissions.get(action)
        if permission is None:
            raise CapabilityAuthorizationDenied(f"unmapped capability action: {action}")
        try:
            self._policy.require(identity, permission)
        except AuthorizationError as exc:
            raise CapabilityAuthorizationDenied(
                f"canonical policy denied {action} via {permission}: {exc}"
            ) from exc
        return CapabilityPolicyDecision(
            capability_id=spec.capability_id,
            capability_version=spec.version,
            action=action,
            canonical_permission=permission,
            allowed=True,
            reason="canonical_policy_allowed",
        )
