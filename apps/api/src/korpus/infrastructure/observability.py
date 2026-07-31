from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest


class Observability:
    """Low-cardinality metrics and optional OpenTelemetry traces.

    Subject, corpus, query, document, and span identifiers are deliberately not
    metric labels. They belong in the tamper-evident audit stream, not a time
    series database.
    """

    def __init__(
        self,
        *,
        service_name: str = "korpus-api",
        otlp_endpoint: str | None = None,
        registry: CollectorRegistry | None = None,
    ) -> None:
        self.registry = registry or CollectorRegistry(auto_describe=True)
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
        self._tracer = self._configure_tracer(service_name, otlp_endpoint)

    @staticmethod
    def _configure_tracer(service_name: str, endpoint: str | None) -> Any:
        from opentelemetry import trace

        if endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            current = trace.get_tracer_provider()
            if current.__class__.__name__ == "ProxyTracerProvider":
                provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
                provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://")))
                )
                trace.set_tracer_provider(provider)
        return trace.get_tracer(service_name)

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

    def observe_http(self, method: str, route: str, status_code: int, duration_seconds: float) -> None:
        status_class = f"{status_code // 100}xx"
        self.http_requests.labels(method=method, route=route, status_class=status_class).inc()
        self.http_latency.labels(method=method, route=route).observe(duration_seconds)

    def observe_answer(self, status: str, reason: str, risk: str) -> None:
        # reason is a closed enum-like set created by the application, not user input.
        self.answers.labels(status=status, reason=reason, risk=risk).inc()

    def export_prometheus(self) -> bytes:
        return generate_latest(self.registry)
