from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from korpus.application.capability_gateway.contracts import payload_digest
from korpus.application.capability_gateway.errors import CapabilityContractError
from korpus.application.capability_gateway.types import (
    CapabilityLifecycle,
    CapabilitySpec,
    ProviderType,
)


@dataclass(frozen=True, slots=True)
class DiscoveredMcpTool:
    """Untrusted discovery data supplied by an MCP server.

    Description and annotations are retained only for operator comparison. They never
    become authorization, effect-class, retry, evidence or egress policy inputs.
    """

    server_identity: str
    tool_name: str
    input_schema: object
    description: str | None = None
    annotations: object | None = None


@dataclass(frozen=True, slots=True)
class ApprovedMcpMapping:
    """Server-owned admission identity for one exact local capability contract."""

    capability_id: str
    capability_version: str
    capability_contract_digest: str
    server_identity: str
    tool_name: str
    input_schema_digest: str


class McpAdmissionStatus(StrEnum):
    MATCH = "MATCH"
    QUARANTINE = "QUARANTINE"


@dataclass(frozen=True, slots=True)
class McpAdmissionDecision:
    status: McpAdmissionStatus
    reason: str
    observed_schema_digest: str | None

    @property
    def admitted(self) -> bool:
        return self.status is McpAdmissionStatus.MATCH


def mcp_input_schema_digest(schema: object) -> str:
    """Digest provider schema as canonical JSON or fail closed on non-finite/non-JSON data."""

    try:
        return payload_digest(schema)
    except CapabilityContractError:
        raise
    except (TypeError, ValueError) as exc:
        raise CapabilityContractError("MCP input schema is not canonical JSON") from exc


def mcp_local_contract_digest(spec: CapabilitySpec) -> str:
    """Bind approval to the complete server-owned local capability contract.

    A capability id/version is an identity, not proof that the authority-bearing fields
    behind that identity stayed unchanged. Hashing the canonical model prevents an old MCP
    approval from silently surviving same-version mutation of effect, policy, egress,
    evidence, retry, idempotency, adapter or operator-approved description fields.
    """

    return payload_digest(spec.model_dump(mode="json"))


def assess_mcp_mapping(
    *,
    spec: CapabilitySpec,
    approved: ApprovedMcpMapping,
    discovered: DiscoveredMcpTool,
) -> McpAdmissionDecision:
    """Compare discovery with the exact local contract without importing provider authority."""

    if spec.provider_type is not ProviderType.MCP:
        return McpAdmissionDecision(McpAdmissionStatus.QUARANTINE, "provider_type_not_mcp", None)
    if spec.lifecycle is not CapabilityLifecycle.ENABLED:
        return McpAdmissionDecision(McpAdmissionStatus.QUARANTINE, "capability_not_enabled", None)
    if approved.capability_id != spec.capability_id or approved.capability_version != spec.version:
        return McpAdmissionDecision(
            McpAdmissionStatus.QUARANTINE,
            "local_capability_binding_mismatch",
            None,
        )
    if approved.capability_contract_digest != mcp_local_contract_digest(spec):
        return McpAdmissionDecision(
            McpAdmissionStatus.QUARANTINE,
            "local_capability_contract_drift",
            None,
        )
    if discovered.server_identity != approved.server_identity:
        return McpAdmissionDecision(McpAdmissionStatus.QUARANTINE, "server_identity_drift", None)
    if discovered.tool_name != approved.tool_name:
        return McpAdmissionDecision(McpAdmissionStatus.QUARANTINE, "tool_identity_drift", None)

    try:
        observed = mcp_input_schema_digest(discovered.input_schema)
    except CapabilityContractError:
        return McpAdmissionDecision(McpAdmissionStatus.QUARANTINE, "schema_not_canonical", None)
    if observed != approved.input_schema_digest:
        return McpAdmissionDecision(McpAdmissionStatus.QUARANTINE, "input_schema_drift", observed)

    # Provider description/annotations remain comparison data only. Their contents cannot
    # widen the exact local contract whose digest was approved above.
    return McpAdmissionDecision(McpAdmissionStatus.MATCH, "exact_local_mapping_match", observed)
