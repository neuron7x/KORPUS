from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CAPABILITY_ID_PATTERN = r"^[a-z][a-z0-9_.-]{2,127}$"
SEMVER_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$"
DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"


class ProviderType(StrEnum):
    INTERNAL = "internal"
    HTTP = "http"
    MCP = "mcp"
    QUEUE = "queue"
    OBJECT_STORE = "object_store"
    CUSTOM = "custom"


class EffectClass(StrEnum):
    READ_LOCAL = "READ_LOCAL"
    READ_REMOTE = "READ_REMOTE"
    WRITE_REMOTE = "WRITE_REMOTE"
    TRANSACTIONAL_SIDE_EFFECT = "TRANSACTIONAL_SIDE_EFFECT"
    PRIVILEGED_ADMIN = "PRIVILEGED_ADMIN"


class EvidenceProfile(StrEnum):
    NONE = "NONE"
    EXECUTION_ONLY = "EXECUTION_ONLY"
    PROVIDER_PROVENANCE = "PROVIDER_PROVENANCE"
    FACTUAL_EVIDENCE = "FACTUAL_EVIDENCE"
    SIGNED_RECEIPT = "SIGNED_RECEIPT"


class DataEgressClass(StrEnum):
    NONE = "NONE"
    PUBLIC_ONLY = "PUBLIC_ONLY"
    POLICY_GATED = "POLICY_GATED"
    RESTRICTED_NO_EGRESS = "RESTRICTED_NO_EGRESS"


class CapabilityLifecycle(StrEnum):
    DISCOVERED_UNTRUSTED = "DISCOVERED_UNTRUSTED"
    DECLARED = "DECLARED"
    VALIDATED = "VALIDATED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class ActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    SERVICE = "service"


class AdapterSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_id: str = Field(min_length=1, max_length=128)
    adapter_version: str = Field(min_length=1, max_length=64)
    configuration_ref: str | None = Field(default=None, max_length=256)


class AuthorizationSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(min_length=1, max_length=128)
    resource_mapper: str = Field(min_length=1, max_length=128)
    requires_explicit_effect_authorization: bool = False


class EvidenceSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: EvidenceProfile
    freshness_seconds: int | None = Field(default=None, ge=0)
    bind_output_digest: bool = False


class TimeoutSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_ms: int = Field(ge=1, le=300_000)


class RetrySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(ge=1, le=10)
    only_safe_errors: bool = True


class IdempotencySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    required: bool
    provider_key_forwarding: bool = False


class DataPolicySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    egress_class: DataEgressClass
    max_request_bytes: int = Field(ge=0, le=10_485_760)
    max_response_bytes: int = Field(ge=0, le=104_857_600)


class CapabilitySpec(BaseModel):
    """Server-owned executable capability declaration.

    Provider metadata is intentionally absent from authorization semantics. The exact
    capability id/version pair, effect class and policy mapping are registered state.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["korpus.capability-spec.v1"]
    capability_id: str = Field(pattern=CAPABILITY_ID_PATTERN)
    version: str = Field(pattern=SEMVER_PATTERN, max_length=64)
    description: str = Field(min_length=1, max_length=1024)
    provider_type: ProviderType
    adapter: AdapterSpec
    effect_class: EffectClass
    input_schema_id: str = Field(min_length=1, max_length=512)
    output_schema_id: str = Field(min_length=1, max_length=512)
    authorization: AuthorizationSpec
    evidence: EvidenceSpec
    timeouts: TimeoutSpec
    retry: RetrySpec
    idempotency: IdempotencySpec
    data_policy: DataPolicySpec
    lifecycle: CapabilityLifecycle

    @model_validator(mode="after")
    def validate_execution_invariants(self) -> CapabilitySpec:
        effectful = self.effect_class in {
            EffectClass.WRITE_REMOTE,
            EffectClass.TRANSACTIONAL_SIDE_EFFECT,
            EffectClass.PRIVILEGED_ADMIN,
        }
        if effectful and not self.idempotency.required:
            raise ValueError("effectful capabilities must require durable idempotency")
        if effectful and not self.authorization.requires_explicit_effect_authorization:
            raise ValueError("effectful capabilities must require explicit effect authorization")
        if self.authorization.requires_explicit_effect_authorization and not effectful:
            raise ValueError("explicit effect authorization is valid only for effectful capabilities")
        if self.idempotency.provider_key_forwarding and not self.idempotency.required:
            raise ValueError("provider idempotency-key forwarding requires idempotency")
        if self.retry.max_attempts > 1 and not self.retry.only_safe_errors:
            raise ValueError("multiple attempts require only_safe_errors=true")
        return self


class IntegrationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["korpus.integration-request.v1"]
    capability_id: str = Field(pattern=CAPABILITY_ID_PATTERN)
    capability_version: str = Field(min_length=1, max_length=64)
    input: dict[str, object]
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)
    dry_run: bool = False


class InvocationActor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_type: ActorType
    subject_id: str = Field(min_length=1, max_length=256)
    session_binding: str | None = Field(default=None, max_length=256)


class InvocationContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["korpus.invocation-context.v1"]
    invocation_id: UUID
    actor: InvocationActor
    request_time: datetime
    service_release: str = Field(min_length=1, max_length=128)
    policy_context_digest: str = Field(pattern=DIGEST_PATTERN)
    trace_id: str | None = Field(default=None, max_length=64)
    purpose: str | None = Field(default=None, max_length=256)

    @field_validator("request_time")
    @classmethod
    def require_timezone_aware_request_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("invocation request_time must be timezone-aware")
        return value
