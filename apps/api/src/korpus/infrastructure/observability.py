from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator, Mapping
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from korpus.infrastructure.pec_observability import PECMetrics

SECURITY_EVENTS = frozenset(
    {
        "auth_denied",
        "authorization_denied",
        "csrf_denied",
        "egress_denied",
        "inference_boundary_denied",
        "rate_limited",
        "webhook_rejected",
        "recovery_failure",
    }
)
SECURITY_OUTCOMES = frozenset({"denied", "error", "observed"})


class Observability:
    """Low-cardinality metrics and optional OpenTelemetry traces."""

    def __init__(
        self,
        *,
        service_name: str = "korpus-api",
        otlp_endpoint: str | None = None,
        registry: CollectorRegistry | None = None,
    ) -> None:
        self.registry = registry or CollectorRegistry(auto_describe=True)
        self.pec = PECMetrics(self.registry)
        self.http_requests = Counter(
            "korpus_http_requests_total",
            "HTTP requests handled by route and status class.",
            ["method", "route", "status_class"],
            registry=self.registry,
        )
        self.http_latency = Histogram(
            "korpus_http_request_duration_seconds",
            "HTTP request latency.",
            ["method", "route"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
            registry=self.registry,
        )
        self.answers = Counter(
            "korpus_answers_total",
            "Answer decisions by bounded outcome labels.",
            ["status", "reason", "risk"],
            registry=self.registry,
        )
        self.retrieval_latency = Histogram(
            "korpus_retrieval_duration_seconds",
            "End-to-end authorized retrieval latency.",
            buckets=(0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1, 3),
            registry=self.registry,
        )
        self.retrieval_candidates = Histogram(
            "korpus_retrieval_candidates",
            "Authorized candidates observed before evidence gates.",
            buckets=(0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512),
            registry=self.registry,
        )
        self.admission_active = Gauge(
            "korpus_admission_active",
            "Currently active answer operations.",
            registry=self.registry,
        )
        self.answer_admission_active = self.admission_active
        self.ingestion_admission_active = Gauge(
            "korpus_ingestion_admission_active",
            "Currently active ingestion operations.",
            registry=self.registry,
        )
        self.audit_anchor_pending = Gauge(
            "korpus_audit_anchor_pending",
            "Committed audit checkpoints awaiting external anchoring.",
            registry=self.registry,
        )
        self.audit_anchor_oldest_seconds = Gauge(
            "korpus_audit_anchor_oldest_pending_seconds",
            "Age of the oldest unanchored checkpoint.",
            registry=self.registry,
        )
        #: Наскільки САМ якір відстав від голови журналу. Черга каже, скільки точок ще
        #: не доставлено, і це твердження ГЛОБАЛЬНЕ: коли інший процес зі своїм шляхом
        #: якоря спорожнив чергу, вона показує нуль, а цей якір стоїть. Виміряно
        #: 31.08.2026: якір розгортання простояв добу на 1024 із 7223 при порожній черзі
        #: й зелених гейтах. `readiness_snapshot` рахував `anchor_gap_events` увесь цей
        #: час — на нього просто ніхто не дивився.
        self.audit_anchor_gap_events = Gauge(
            "korpus_audit_anchor_gap_events",
            "Events between the external anchor and the ledger head.",
            registry=self.registry,
        )
        self.audit_anchor_reconcile_failures = Counter(
            "korpus_audit_anchor_reconcile_failures_total",
            "Audit-anchor reconciliation failures.",
            ["error_class"],
            registry=self.registry,
        )
        self.security_events = Counter(
            "korpus_security_events_total",
            "Bounded security decisions.",
            ["event", "outcome"],
            registry=self.registry,
        )
        self.requested_otlp_endpoint = otlp_endpoint
        self._provider, self._tracer = self._configure_tracer(service_name, otlp_endpoint)

    def telemetry_status(self) -> dict[str, object]:
        """Report requested-vs-active trace export; audit durability is independent."""
        if not self.requested_otlp_endpoint:
            return {"traces": "DISABLED", "endpoint": None}
        if self._provider is None:
            return {
                "traces": "REQUESTED_NOT_ACTIVE",
                "endpoint": self.requested_otlp_endpoint,
                "reason": "a tracer provider was already installed in this process, so "
                "the configured OTLP exporter was not attached and no span reaches it",
            }
        return {"traces": "ACTIVE", "endpoint": self.requested_otlp_endpoint}

    @staticmethod
    def _configure_tracer(service_name: str, endpoint: str | None) -> tuple[Any | None, Any]:
        from opentelemetry import trace

        provider: Any | None = None
        if endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            current = trace.get_tracer_provider()
            if current.__class__.__name__ == "ProxyTracerProvider":
                provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
                provider.add_span_processor(
                    BatchSpanProcessor(
                        OTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))
                    )
                )
                trace.set_tracer_provider(provider)
        return provider, trace.get_tracer(service_name)

    @contextlib.contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
        with self._tracer.start_as_current_span(name, attributes=attributes or {}) as span:
            yield span

    @contextlib.contextmanager
    def measure_retrieval(self) -> Iterator[None]:
        started = time.monotonic()
        with self.span("korpus.retrieval"):
            try:
                yield
            finally:
                self.retrieval_latency.observe(time.monotonic() - started)

    def observe_http(
        self, method: str, route: str, status_code: int, duration_seconds: float
    ) -> None:
        status_class = f"{status_code // 100}xx"
        self.http_requests.labels(method=method, route=route, status_class=status_class).inc()
        self.http_latency.labels(method=method, route=route).observe(duration_seconds)

    def observe_answer(self, status: str, reason: str, risk: str) -> None:
        self.answers.labels(status=status, reason=reason, risk=risk).inc()

    def observe_readiness(self, snapshot: Mapping[str, object]) -> None:
        """Зіставлення полів знімка з метриками — окремо, бо саме воно й розійшлося.

        Цикл спостерігав довжину ЧЕРГИ й не спостерігав відставання САМОГО якоря, хоча
        `readiness_snapshot` рахував обидва. Поки це зіставлення жило рядками всередині
        циклу, жоден тест не міг сказати, що воно правильне.
        """
        self.observe_anchor_backlog(
            int(snapshot["pending_anchor_events"]),  # type: ignore[call-overload]
            float(snapshot["oldest_pending_seconds"]),  # type: ignore[arg-type]
            int(snapshot["anchor_gap_events"]),  # type: ignore[call-overload]
        )

    def observe_anchor_backlog(self, pending: int, oldest_seconds: float, gap: int = 0) -> None:
        self.audit_anchor_pending.set(pending)
        self.audit_anchor_oldest_seconds.set(oldest_seconds)
        self.audit_anchor_gap_events.set(gap)

    def observe_anchor_reconcile_failure(self, error: BaseException) -> None:
        self.audit_anchor_reconcile_failures.labels(error_class=type(error).__name__).inc()

    def observe_security_event(self, event: str, outcome: str = "denied") -> None:
        if event not in SECURITY_EVENTS or outcome not in SECURITY_OUTCOMES:
            raise ValueError("security metric labels are outside the bounded vocabulary")
        self.security_events.labels(event=event, outcome=outcome).inc()

    def export_prometheus(self) -> bytes:
        return generate_latest(self.registry)

    def close(self) -> None:
        if self._provider is not None:
            self._provider.shutdown()
