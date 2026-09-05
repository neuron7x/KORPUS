from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from korpus.application.capability_gateway.contracts import capability_spec_digest
from korpus.application.capability_gateway.errors import CapabilityRegistrationError
from korpus.application.capability_gateway.types import (
    CAPABILITY_ID_PATTERN,
    DIGEST_PATTERN,
    SEMVER_PATTERN,
    CapabilityLifecycle,
    CapabilitySpec,
    EffectClass,
)

_EFFECTFUL = frozenset(
    {
        EffectClass.WRITE_REMOTE,
        EffectClass.TRANSACTIONAL_SIDE_EFFECT,
        EffectClass.PRIVILEGED_ADMIN,
    }
)
CapabilityKey = tuple[str, str]


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

    def __init__(
        self,
        declarations: Iterable[EffectSafetyDeclaration] | None = None,
    ) -> None:
        self._declarations: dict[CapabilityKey, EffectSafetyDeclaration] = {}
        for declaration in declarations or ():
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


def effect_safety_graph_errors(
    specs: Iterable[CapabilitySpec],
    safety: EffectSafetyRegistry,
) -> tuple[str, ...]:
    """Validate exact declarations plus cross-capability compensation dependencies.

    A declaration can be locally well-formed while naming an unusable compensation target.
    This graph-level check therefore runs over the complete server-owned capability set used
    by deployment/runtime composition. Compensation edges must also be acyclic: recovery
    needs a well-founded terminal plan, not a locally valid A->B->...->A loop.
    This grants no authority; it only rejects unsafe plans.
    """

    ordered = tuple(specs)
    by_key = {(spec.capability_id, spec.version): spec for spec in ordered}
    errors: list[str] = []
    compensation_edges: dict[CapabilityKey, CapabilityKey] = {}

    for spec in ordered:
        if spec.lifecycle is not CapabilityLifecycle.ENABLED or spec.effect_class not in _EFFECTFUL:
            continue
        source_key_tuple = spec.capability_id, spec.version
        source_key = _format_capability_key(source_key_tuple)
        try:
            declaration = safety.resolve_exact(spec)
        except CapabilityRegistrationError as exc:
            errors.append(f"{source_key}: {exc}")
            continue

        if declaration.compensation_mode is not CompensationMode.COMPENSATING_ACTION:
            continue

        target_id = declaration.compensation_capability_id
        target_version = declaration.compensation_capability_version
        if target_id is None or target_version is None:
            errors.append(
                f"{source_key}: compensation capability identity is incomplete"
            )
            continue

        target_key_tuple = target_id, target_version
        target = by_key.get(target_key_tuple)
        target_key = _format_capability_key(target_key_tuple)
        if target is None:
            errors.append(
                f"{source_key}: compensation capability is not registered: {target_key}"
            )
            continue
        if target.lifecycle is not CapabilityLifecycle.ENABLED:
            errors.append(
                f"{source_key}: compensation capability is not enabled: "
                f"{target_key} ({target.lifecycle.value})"
            )
            continue
        if target.effect_class not in _EFFECTFUL:
            errors.append(
                f"{source_key}: compensation capability must be effectful: {target_key}"
            )
            continue

        compensation_edges[source_key_tuple] = target_key_tuple

    errors.extend(_compensation_cycle_errors(compensation_edges))
    return tuple(sorted(errors))


def _compensation_cycle_errors(edges: Mapping[CapabilityKey, CapabilityKey]) -> tuple[str, ...]:
    """Return deterministic errors for cycles in a functional compensation graph."""

    visited: set[CapabilityKey] = set()
    active_index: dict[CapabilityKey, int] = {}
    stack: list[CapabilityKey] = []
    errors: set[str] = set()

    def visit(node: CapabilityKey) -> None:
        if node in active_index:
            cycle = stack[active_index[node] :] + [node]
            rendered = " -> ".join(_format_capability_key(item) for item in cycle)
            errors.add(f"compensation cycle detected: {rendered}")
            return
        if node in visited:
            return

        active_index[node] = len(stack)
        stack.append(node)
        target = edges.get(node)
        if target is not None:
            visit(target)
        stack.pop()
        active_index.pop(node, None)
        visited.add(node)

    for node in sorted(edges):
        visit(node)
    return tuple(sorted(errors))


def _format_capability_key(key: CapabilityKey) -> str:
    return f"{key[0]}@{key[1]}"
