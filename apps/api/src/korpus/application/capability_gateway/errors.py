from __future__ import annotations


class CapabilityGatewayError(RuntimeError):
    reason = "capability_gateway_error"


class CapabilityRegistrationError(CapabilityGatewayError):
    reason = "capability_registration_error"


class CapabilityNotFound(CapabilityGatewayError):
    reason = "capability_not_found"


class CapabilityUnavailable(CapabilityGatewayError):
    reason = "capability_not_enabled"


class CapabilityContractError(CapabilityGatewayError):
    reason = "capability_contract_error"


class CapabilityPolicyIndeterminate(CapabilityGatewayError):
    """Canonical policy could not produce a trustworthy resource-scoped decision."""

    reason = "capability_policy_indeterminate"


class CapabilityAuthorizationDenied(PermissionError):
    reason = "capability_authorization_denied"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)
