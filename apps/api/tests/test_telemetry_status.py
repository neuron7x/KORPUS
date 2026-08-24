"""Telemetry configured and going nowhere must not look like telemetry off.

`Observability._configure_tracer` attaches an OTLP exporter only while the global
tracer provider is still the proxy. The guard is correct — a second install would
replace whatever the process already runs with — but it means a configured
`otlp_endpoint` can be ignored, and nothing distinguished the two states. An operator
reading the config believes traces exist; they do not, and no error was ever raised.

Reported rather than enforced, deliberately. The release policy allows telemetry
*display* to degrade provided the underlying event stays durably available, and it
does: the audit chain is not the tracer. Refusing to start over a missing collector
would take a working corpus offline for a reason that does not affect any answer.
"""

from __future__ import annotations

from korpus.infrastructure.observability import Observability


def test_telemetry_is_reported_as_disabled_when_no_endpoint_is_configured() -> None:
    status = Observability(service_name="korpus-test").telemetry_status()

    assert status["traces"] == "DISABLED"
    assert status["endpoint"] is None


def test_a_configured_endpoint_that_could_not_be_attached_says_so() -> None:
    """The state the guard creates and nothing used to name.

    The first instance installs a provider; a second one with an endpoint finds the
    provider already in place and attaches nothing. Before this, both reported the
    same thing — which is to say, nothing.
    """
    first = Observability(service_name="korpus-first", otlp_endpoint="http://collector:4317")
    second = Observability(service_name="korpus-second", otlp_endpoint="http://collector:4317")

    try:
        first_status = first.telemetry_status()
        second_status = second.telemetry_status()

        assert {first_status["traces"], second_status["traces"]} <= {
            "ACTIVE",
            "REQUESTED_NOT_ACTIVE",
        }
        # Whichever lost the race, exactly one of them can own the global provider, and
        # the loser must not report ACTIVE.
        assert [first_status["traces"], second_status["traces"]].count("ACTIVE") <= 1
        inactive = [s for s in (first_status, second_status) if s["traces"] != "ACTIVE"]
        for status in inactive:
            assert status["endpoint"] == "http://collector:4317"
            assert "no span reaches it" in str(status["reason"])
    finally:
        first.close()
        second.close()


def test_the_requested_endpoint_is_retained_for_diagnosis() -> None:
    """Without it, "not active" cannot be told from "never asked for"."""
    observability = Observability(
        service_name="korpus-recorded", otlp_endpoint="http://collector:4317"
    )

    try:
        assert observability.requested_otlp_endpoint == "http://collector:4317"
    finally:
        observability.close()


def test_metrics_remain_available_regardless_of_trace_export() -> None:
    """Prometheus scraping and OTLP export are separate paths; one must not mask the other."""
    observability = Observability(service_name="korpus-metrics")

    observability.observe_http("GET", "/v1/answer", 200, 0.01)

    assert b"korpus_http_requests_total" in observability.export_prometheus()
