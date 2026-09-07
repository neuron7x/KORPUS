"""Governed capability gateway application core.

The package is deliberately protocol-independent. External transports are adapters and
must not define authorization, capability identity, evidence authority, or retry safety.
"""

from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.types import CapabilitySpec, IntegrationRequest

__all__ = ["CapabilityRegistry", "CapabilitySpec", "IntegrationRequest"]
