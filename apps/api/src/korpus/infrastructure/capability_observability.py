from __future__ import annotations

from contextlib import AbstractContextManager

from prometheus_client import Counter, Histogram

from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.invoke import IntegrationResult
from korpus.application.capability_gateway.types import CapabilitySpec
from korpus.infrastructure.observability import Observability

_KNOWN_ERROR_CODES = frozenset(
    {
        "CAPABILITY_UNKNOWN",
        "CAPABILITY_DISABLED",
        "RESOURCE_MAPPER_UNKNOWN",
        "RESOURCE_MAPPING_FAILED",
        "POLICY_DENIED",
        "INPUT_SCHEMA_INVALID",
        "DRY_RUN_NOT_ADMITTED",
        "EGRESS_DENIED",
        "EGRESS_POLICY_FAILED",
        "EFFECT_AUTH_REQUIRED",
        "IDEMPOTENCY_REQUIRED",
        "IDEMPOTENCY_CONFLICT",
        "IDEMPOTENT_REPLAY_REQUIRES_RECONCILIATION",
        "ADAPTER_NOT_REGISTERED",
        "ADAPTER_FAILURE",
        "ADAPTER_TIMEOUT",
        "OUTPUT_SCHEMA_INVALID",
        "EVIDENCE_MISSING",
        "EVIDENCE_INVALID",
        "EVIDENCE_STALE",
        "AUDIT_APPEND_FAILED",
        "INTERNAL_ERROR",
    }
)


class CapabilityObservability:
    """Bounded capability metrics and traces on the existing observability registry.

    Prometheus labels intentionally exclude subject, logical resource, capability id and
    capability version. Canonical id/version are allowed only as trace attributes after an
    exact registry resolution; unknown caller-controlled ids are never copied to telemetry.
    """

    def __init__(self, observability: Observability) -> None:
        self._observability = observability
        self._invocations = Counter(
            "korpus_capability_invocations_total",
            "Capability invocations by bounded governed outcome dimensions.",
            ["outcome", "error_code", "effect_class", "provider_type"],
            registry=observability.registry,
        )
        self._latency = Histogram(
            "korpus_capability_invocation_duration_seconds",
            "End-to-end governed capability invocation latency.",
            ["outcome", "effect_class", "provider_type"],
            buckets=(0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30),
            registry=observability.registry,
        )
        self._outcome_unknown = Counter(
            "korpus_capability_outcome_unknown_total",
            "Capability invocations requiring effect reconciliation.",
            ["effect_class", "provider_type"],
            registry=observability.registry,
        )

    def invocation_span(self, spec: CapabilitySpec | None) -> AbstractContextManager[object]:
        attributes: dict[str, object] = {"korpus.capability.resolved": spec is not None}
        if spec is not None:
            attributes.update(
                {
                    "korpus.capability.id": spec.capability_id,
                    "korpus.capability.version": spec.version,
                    "korpus.capability.effect_class": spec.effect_class.value,
                    "korpus.capability.provider_type": spec.provider_type.value,
                    "korpus.capability.adapter_id": spec.adapter.adapter_id,
                    "korpus.capability.adapter_version": spec.adapter.adapter_version,
                }
            )
        return self._observability.span("korpus.capability.invoke", attributes)

    def observe_invocation(
        self,
        *,
        spec: CapabilitySpec | None,
        result: IntegrationResult,
        duration_seconds: float,
    ) -> None:
        effect_class = spec.effect_class.value if spec is not None else "unknown"
        provider_type = spec.provider_type.value if spec is not None else "unknown"
        error_code = self._bounded_error_code(result.error_code)
        outcome = result.outcome.value
        self._invocations.labels(
            outcome=outcome,
            error_code=error_code,
            effect_class=effect_class,
            provider_type=provider_type,
        ).inc()
        self._latency.labels(
            outcome=outcome,
            effect_class=effect_class,
            provider_type=provider_type,
        ).observe(max(0.0, duration_seconds))
        if result.outcome is InvocationOutcome.OUTCOME_UNKNOWN:
            self._outcome_unknown.labels(
                effect_class=effect_class,
                provider_type=provider_type,
            ).inc()

    @staticmethod
    def _bounded_error_code(value: str | None) -> str:
        if value is None:
            return "none"
        return value if value in _KNOWN_ERROR_CODES else "other"
