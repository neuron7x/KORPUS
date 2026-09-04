from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from korpus.application.capability_gateway.contracts import capability_spec_digest
from korpus.application.capability_gateway.errors import CapabilityRegistrationError
from korpus.application.capability_gateway.types import (
    CAPABILITY_ID_PATTERN,
    DIGEST_PATTERN,
    SEMVER_PATTERN,
    CapabilitySpec,
)


class CompensationMode(StrEnum):
    PROVIDER_NATIVE = "PROVIDER_NATIVE"
    COMPENSATING_ACTION = "COMPENSATING_ACTION"
    NONE = "NONE"


class ReconciliationMode(StrEnum):
    PROVIDER_STATUS_QUERY = "PROVIDER_STATUS_QUERY"
    PROVIDER_IDEMPOTENCY_LOOKUP = "PROVIDER_IDEMPOTENCY_LOOKUP"
    MANUAL = "MANUAL"


class EffectSafetyDeclaration(BaseModel):
    """Server-owned safety declaration exact-bound to one capability contract.

    This object never grants authorization. It makes rollback/irreversibility and recovery
    semantics explicit before an effectful capability can be deployment-admitted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["korpus.effect-safety.v1"] = "korpus.effect-safety.v1"
    capability_id: str = Field(pattern=CAPABILITY_ID_PATTERN)
    capability_version: str = Field(pattern=SEMVER_PATTERN, max_length=64)
    capability_contract_digest: str = Field(pattern=DIGEST_PATTERN)
    compensation_mode: CompensationMode
    irreversible: bool
    reconciliation_mode: ReconciliationMode
    compensation_capability_id: str | None = Field(
        default=None,
        pattern=CAPABILITY_ID_PATTERN,
    )
    compensation_capability_version: str | None = Field(
        default=None,
        pattern=SEMVER_PATTERN,
        max_length=64,
    )
    operator_rationale: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_safety_semantics(self) -> EffectSafetyDeclaration:
        compensation_identity = (
            self.compensation_capability_id,
            self.compensation_capability_version,
        )
        if self.compensation_mode is CompensationMode.COMPENSATING_ACTION:
            if any(value is None for value in compensation_identity):
                raise ValueError(
                    "compensating action requires exact compensation capability id/version"
                )
            if compensation_identity == (self.capability_id, self.capability_version):
                raise ValueError("compensating action cannot self-reference the same capability")
        elif any(value is not None for value in compensation_identity):
            raise ValueError(
                "compensation capability identity is valid only for COMPENSATING_ACTION"
            )

        if self.compensation_mode is CompensationMode.NONE and not self.irreversible:
            raise ValueError("no-compensation effect must be explicitly irreversible")
        return self

    @classmethod
    def for_spec(
        cls,
        spec: CapabilitySpec,
        *,
        compensation_mode: CompensationMode,
        irreversible: bool,
        reconciliation_mode: ReconciliationMode,
        operator_rationale: str,
        compensation_capability_id: str | None = None,
        compensation_capability_version: str | None = None,
    ) -> EffectSafetyDeclaration:
        return cls(
            capability_id=spec.capability_id,
            capability_version=spec.version,
            capability_contract_digest=capability_spec_digest(spec),
            compensation_mode=compensation_mode,
            irreversible=irreversible,
            reconciliation_mode=reconciliation_mode,
            compensation_capability_id=compensation_capability_id,
            compensation_capability_version=compensation_capability_version,
            operator_rationale=operator_rationale,
        )


class EffectSafetyRegistry:
    """Exact immutable registry of deployment-owned side-effect safety declarations."""

    def __init__(self, declarations: list[EffectSafetyDeclaration] | None = None) -> None:
        self._declarations: dict[tuple[str, str], EffectSafetyDeclaration] = {}
        for declaration in declarations or []:
            self.register(declaration)

    def register(self, declaration: EffectSafetyDeclaration) -> None:
        key = declaration.capability_id, declaration.capability_version
        if key in self._declarations:
            raise CapabilityRegistrationError(
                f"duplicate effect safety declaration: {key[0]}@{key[1]}"
            )
        self._declarations[key] = declaration

    def resolve_exact(self, spec: CapabilitySpec) -> EffectSafetyDeclaration:
        key = spec.capability_id, spec.version
        try:
            declaration = self._declarations[key]
        except KeyError as exc:
            raise CapabilityRegistrationError(
                f"effect safety declaration is not registered: {key[0]}@{key[1]}"
            ) from exc
        if declaration.capability_contract_digest != capability_spec_digest(spec):
            raise CapabilityRegistrationError(
                f"effect safety declaration contract drift: {key[0]}@{key[1]}"
            )
        return declaration
