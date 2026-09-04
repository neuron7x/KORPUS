from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from korpus.application.capability_gateway.adapters import AdapterRegistry
from korpus.application.capability_gateway.audit import CapabilityAuditSink, InvocationOutcome
from korpus.application.capability_gateway.context import (
    bind_invocation_resource,
    build_invocation_context,
)
from korpus.application.capability_gateway.contracts import validate_request_binding
from korpus.application.capability_gateway.effect_safety import EffectSafetyRegistry
from korpus.application.capability_gateway.effects import (
    EffectGuard,
    EffectLedger,
    EffectState,
    IdempotencyConflict,
    effectful,
    prepare_effect_guard,
)
from korpus.application.capability_gateway.errors import (
    CapabilityAuthorizationDenied,
    CapabilityContractError,
    CapabilityNotFound,
    CapabilityPolicyIndeterminate,
    CapabilityRegistrationError,
    CapabilityUnavailable,
)
from korpus.application.capability_gateway.execution import CapabilityExecutor, SchemaValidator
from korpus.application.capability_gateway.policy import (
    CapabilityPolicyBridge,
    CapabilityPolicyDecision,
)
from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.result import (
    CapabilityResultEmitter,
    ExecutionMaterial,
    IntegrationResult,
    InvocationFrame,
    early_result,
)
from korpus.application.capability_gateway.types import (
    CapabilityLifecycle,
    CapabilitySpec,
    IntegrationRequest,
    InvocationContext,
)
from korpus.domain.models import Identity

ResourceMapper = Callable[[Identity, CapabilitySpec, IntegrationRequest], str]
ResourceBinding = tuple[InvocationContext, str]


class CapabilityEgressGuard(Protocol):
    def check(
        self,
        *,
        identity: Identity,
        spec: CapabilitySpec,
        request: IntegrationRequest,
        logical_resource: str,
    ) -> None: ...


class EffectAuthorizer(Protocol):
    def authorize(
        self,
        *,
        identity: Identity,
        spec: CapabilitySpec,
        logical_resource: str,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class CapabilityGatewayPorts:
    registry: CapabilityRegistry
    policy: CapabilityPolicyBridge
    adapters: AdapterRegistry
    schemas: SchemaValidator
    resource_mappers: Mapping[str, ResourceMapper]
    egress: CapabilityEgressGuard
    effect_authorizer: EffectAuthorizer
    effects: EffectLedger
    audit: CapabilityAuditSink
    effect_safety: EffectSafetyRegistry | None = None


_LEGACY_REQUIRED_PORT_KEYS = frozenset(
    {
        "registry",
        "policy",
        "adapters",
        "schemas",
        "resource_mappers",
        "egress",
        "effect_authorizer",
        "effects",
        "audit",
    }
)
_LEGACY_OPTIONAL_PORT_KEYS = frozenset({"effect_safety"})


class CapabilityGateway:
    """Application-layer PEP; later stages can only reduce returnability, never authority."""

    def __init__(
        self,
        ports: CapabilityGatewayPorts | None = None,
        **legacy_ports: object,
    ) -> None:
        structured_composition = ports is not None
        explicit_legacy_safety = "effect_safety" in legacy_ports
        resolved = _normalize_ports(ports, legacy_ports)
        safety = resolved.effect_safety or EffectSafetyRegistry()
        if structured_composition or explicit_legacy_safety:
            _require_effect_safety(resolved.registry, safety)
        self._registry = resolved.registry
        self._policy = resolved.policy
        self._resource_mappers = dict(resolved.resource_mappers)
        self._egress = resolved.egress
        self._effect_authorizer = resolved.effect_authorizer
        self._effects = resolved.effects
        self._effect_safety = safety
        self._emitter = CapabilityResultEmitter(resolved.audit)
        self._executor = CapabilityExecutor(
            adapters=resolved.adapters,
            schemas=resolved.schemas,
            effects=resolved.effects,
            emitter=self._emitter,
        )

    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult:
        started_at = datetime.now(UTC)
        resolved = self._resolve(request)
        if isinstance(resolved, IntegrationResult):
            return resolved
        bound = self._bind_resource(identity, resolved, request, started_at)
        if isinstance(bound, IntegrationResult):
            return bound
        context, logical_resource = bound
        decision = self._authorize(identity, resolved, context, logical_resource)
        if isinstance(decision, IntegrationResult):
            return decision
        frame = InvocationFrame(
            identity=identity,
            request=request,
            started_at=started_at,
            spec=resolved,
            context=context,
            decision=decision,
            logical_resource=logical_resource,
        )
        blocked = self._pre_execution(frame)
        if blocked is not None:
            return blocked
        guard = self._prepare_effect(frame)
        if isinstance(guard, IntegrationResult):
            return guard
        if not guard.should_execute:
            return self._replay_result(frame, guard)
        return self._executor.execute(frame, guard)

    def _resolve(self, request: IntegrationRequest) -> CapabilitySpec | IntegrationResult:
        try:
            return self._registry.resolve_exact(request.capability_id, request.capability_version)
        except CapabilityNotFound:
            return early_result(InvocationOutcome.DENIED, "CAPABILITY_UNKNOWN")
        except CapabilityUnavailable:
            return early_result(InvocationOutcome.DENIED, "CAPABILITY_DISABLED")
        except Exception:
            return early_result(InvocationOutcome.FAILED, "INTERNAL_ERROR")

    def _bind_resource(
        self,
        identity: Identity,
        spec: CapabilitySpec,
        request: IntegrationRequest,
        started_at: datetime,
    ) -> ResourceBinding | IntegrationResult:
        context = self._build_context(identity, spec, started_at)
        if isinstance(context, IntegrationResult):
            return context
        resource = self._map_resource(identity, spec, request, context)
        if isinstance(resource, IntegrationResult):
            return resource
        return self._bind_context(identity, spec, context, resource)

    @staticmethod
    def _build_context(
        identity: Identity,
        spec: CapabilitySpec,
        started_at: datetime,
    ) -> InvocationContext | IntegrationResult:
        try:
            return build_invocation_context(identity=identity, spec=spec, request_time=started_at)
        except Exception:
            return early_result(InvocationOutcome.FAILED, "INTERNAL_ERROR")

    def _map_resource(
        self,
        identity: Identity,
        spec: CapabilitySpec,
        request: IntegrationRequest,
        context: InvocationContext,
    ) -> str | IntegrationResult:
        mapper = self._resource_mappers.get(spec.authorization.resource_mapper)
        if mapper is None:
            return early_result(
                InvocationOutcome.FAILED,
                "RESOURCE_MAPPER_UNKNOWN",
                invocation_id=context.invocation_id,
            )
        try:
            logical_resource = mapper(identity, spec, request)
        except (KeyError, TypeError, ValueError):
            return early_result(
                InvocationOutcome.REJECTED,
                "INPUT_SCHEMA_INVALID",
                invocation_id=context.invocation_id,
            )
        except Exception:
            return early_result(
                InvocationOutcome.FAILED,
                "RESOURCE_MAPPING_FAILED",
                invocation_id=context.invocation_id,
            )
        if not isinstance(logical_resource, str) or not logical_resource.strip():
            return early_result(
                InvocationOutcome.FAILED,
                "RESOURCE_MAPPING_FAILED",
                invocation_id=context.invocation_id,
            )
        return logical_resource.strip()

    @staticmethod
    def _bind_context(
        identity: Identity,
        spec: CapabilitySpec,
        context: InvocationContext,
        logical_resource: str,
    ) -> ResourceBinding | IntegrationResult:
        try:
            bound = bind_invocation_resource(
                context,
                identity=identity,
                spec=spec,
                logical_resource=logical_resource,
            )
        except Exception:
            return early_result(
                InvocationOutcome.FAILED,
                "RESOURCE_MAPPING_FAILED",
                invocation_id=context.invocation_id,
            )
        return bound, logical_resource

    def _authorize(
        self,
        identity: Identity,
        spec: CapabilitySpec,
        context: InvocationContext,
        logical_resource: str,
    ) -> CapabilityPolicyDecision | IntegrationResult:
        try:
            return self._policy.authorize_resource(
                identity,
                spec,
                logical_resource=logical_resource,
            )
        except CapabilityAuthorizationDenied:
            return early_result(
                InvocationOutcome.DENIED,
                "POLICY_DENIED",
                invocation_id=context.invocation_id,
            )
        except CapabilityPolicyIndeterminate:
            return early_result(
                InvocationOutcome.FAILED,
                "POLICY_UNKNOWN",
                invocation_id=context.invocation_id,
            )
        except Exception:
            return early_result(
                InvocationOutcome.FAILED,
                "POLICY_UNKNOWN",
                invocation_id=context.invocation_id,
            )

    def _pre_execution(self, frame: InvocationFrame) -> IntegrationResult | None:
        try:
            validate_request_binding(frame.request, frame.spec)
            self._executor.validate_input(frame.spec.input_schema_id, frame.request.input)
        except (CapabilityContractError, ValueError):
            return self._emitter.emit(frame, InvocationOutcome.REJECTED, "INPUT_SCHEMA_INVALID")
        except Exception:
            return self._emitter.emit(frame, InvocationOutcome.FAILED, "INTERNAL_ERROR")
        if frame.request.dry_run:
            return self._emitter.emit(frame, InvocationOutcome.REJECTED, "DRY_RUN_NOT_ADMITTED")
        return self._guard_egress(frame)

    def _guard_egress(self, frame: InvocationFrame) -> IntegrationResult | None:
        try:
            self._egress.check(
                identity=frame.identity,
                spec=frame.spec,
                request=frame.request,
                logical_resource=frame.logical_resource,
            )
        except PermissionError:
            return self._emitter.emit(frame, InvocationOutcome.DENIED, "EGRESS_DENIED")
        except Exception:
            return self._emitter.emit(frame, InvocationOutcome.FAILED, "EGRESS_POLICY_FAILED")
        return None

    def _effect_authorized(self, frame: InvocationFrame) -> bool:
        if not effectful(frame.spec):
            return True
        try:
            decision = self._effect_authorizer.authorize(
                identity=frame.identity,
                spec=frame.spec,
                logical_resource=frame.logical_resource,
            )
        except Exception:
            return False
        # Authority is granted only by the protocol's literal boolean allow decision.
        # Truthy strings, integers, sentinels and provider-shaped objects fail closed.
        return decision is True

    def _prepare_effect(self, frame: InvocationFrame) -> EffectGuard | IntegrationResult:
        explicit = self._effect_authorized(frame)
        if effectful(frame.spec) and not explicit:
            return self._emitter.emit(frame, InvocationOutcome.DENIED, "EFFECT_AUTH_REQUIRED")
        try:
            return prepare_effect_guard(
                identity=frame.identity,
                spec=frame.spec,
                request=frame.request,
                logical_resource=frame.logical_resource,
                invocation_id=str(frame.context.invocation_id),
                ledger=self._effects,
                explicit_effect_authorized=explicit,
            )
        except PermissionError:
            return self._emitter.emit(frame, InvocationOutcome.DENIED, "EFFECT_AUTH_REQUIRED")
        except CapabilityContractError:
            return self._emitter.emit(frame, InvocationOutcome.REJECTED, "IDEMPOTENCY_REQUIRED")
        except IdempotencyConflict:
            return self._emitter.emit(frame, InvocationOutcome.REJECTED, "IDEMPOTENCY_CONFLICT")
        except Exception:
            return self._emitter.emit(frame, InvocationOutcome.FAILED, "INTERNAL_ERROR")

    def _replay_result(self, frame: InvocationFrame, guard: EffectGuard) -> IntegrationResult:
        existing = guard.reservation.record if guard.reservation is not None else None
        pending = existing is not None and existing.state in {
            EffectState.PENDING,
            EffectState.OUTCOME_UNKNOWN,
        }
        outcome = InvocationOutcome.OUTCOME_UNKNOWN if pending else InvocationOutcome.FAILED
        return self._emitter.emit(
            frame,
            outcome,
            "IDEMPOTENT_REPLAY_REQUIRES_RECONCILIATION",
            ExecutionMaterial(idempotency_binding=guard.binding_digest),
        )


def _require_effect_safety(
    registry: CapabilityRegistry,
    safety: EffectSafetyRegistry,
) -> None:
    errors: list[str] = []
    for spec in registry.all_specs():
        if spec.lifecycle is not CapabilityLifecycle.ENABLED or not effectful(spec):
            continue
        try:
            safety.resolve_exact(spec)
        except CapabilityRegistrationError as exc:
            errors.append(str(exc))
    if errors:
        detail = "; ".join(sorted(errors))
        raise CapabilityRegistrationError(f"effectful gateway composition rejected: {detail}")


def _normalize_ports(
    ports: CapabilityGatewayPorts | None,
    legacy: Mapping[str, object],
) -> CapabilityGatewayPorts:
    if ports is not None:
        if legacy:
            raise TypeError("CapabilityGateway accepts either ports or legacy keyword ports, not both")
        return ports
    keys = frozenset(legacy)
    allowed = _LEGACY_REQUIRED_PORT_KEYS | _LEGACY_OPTIONAL_PORT_KEYS
    if not _LEGACY_REQUIRED_PORT_KEYS.issubset(keys) or not keys.issubset(allowed):
        missing = sorted(_LEGACY_REQUIRED_PORT_KEYS - keys)
        extra = sorted(keys - allowed)
        raise TypeError(f"invalid CapabilityGateway port set: missing={missing}, extra={extra}")
    return CapabilityGatewayPorts(
        registry=cast(CapabilityRegistry, legacy["registry"]),
        policy=cast(CapabilityPolicyBridge, legacy["policy"]),
        adapters=cast(AdapterRegistry, legacy["adapters"]),
        schemas=cast(SchemaValidator, legacy["schemas"]),
        resource_mappers=cast(Mapping[str, ResourceMapper], legacy["resource_mappers"]),
        egress=cast(CapabilityEgressGuard, legacy["egress"]),
        effect_authorizer=cast(EffectAuthorizer, legacy["effect_authorizer"]),
        effects=cast(EffectLedger, legacy["effects"]),
        audit=cast(CapabilityAuditSink, legacy["audit"]),
        effect_safety=cast(EffectSafetyRegistry | None, legacy.get("effect_safety")),
    )


__all__ = ["CapabilityGateway", "CapabilityGatewayPorts", "IntegrationResult"]
