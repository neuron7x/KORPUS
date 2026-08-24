from __future__ import annotations

import pytest

from scripts.gcp.canary_metrics import evaluate, summarize


def _payload(*series: tuple[str, list[int]]) -> dict:
    return {
        "timeSeries": [
            {
                "metric": {"labels": {"response_code_class": response_class}},
                "points": [{"value": {"int64Value": str(value)}} for value in values],
            }
            for response_class, values in series
        ]
    }


def test_canary_metrics_pass_only_with_sufficient_clean_samples() -> None:
    result = summarize(_payload(("2xx", [12, 10])), "korpus-api", "api-r2", 20, 0.01)
    assert result.passed is True
    assert result.samples == 22
    assert result.successful_requests == 22
    assert result.server_errors == 0


def test_canary_metrics_fail_closed_on_insufficient_samples() -> None:
    result = summarize(_payload(("2xx", [19])), "korpus-api", "api-r2", 20, 0.01)
    assert result.passed is False
    assert result.reason == "INSUFFICIENT_SUCCESS_SAMPLES"


def test_canary_metrics_reject_server_error_rate() -> None:
    result = summarize(_payload(("2xx", [99]), ("5xx", [1])), "korpus-api", "api-r2", 20, 0.005)
    assert result.passed is False
    assert result.reason == "SERVER_ERROR_RATE_EXCEEDED"
    assert result.error_rate == pytest.approx(0.01)


def test_canary_metrics_reject_invalid_counter() -> None:
    with pytest.raises(ValueError):
        summarize(_payload(("2xx", [-1])), "korpus-api", "api-r2", 1, 0.01)


def test_canary_metrics_do_not_treat_client_errors_as_success_samples() -> None:
    result = summarize(_payload(("4xx", [30])), "korpus-api", "api-r2", 20, 0.01)
    assert result.passed is False
    assert result.samples == 30
    assert result.successful_requests == 0
    assert result.reason == "INSUFFICIENT_SUCCESS_SAMPLES"


def test_canary_metrics_reject_filter_injection_identifiers() -> None:
    with pytest.raises(ValueError):
        evaluate(
            'proj" OR true',
            "api-r2",
            "web-r2",
            minimum_samples=1,
            maximum_error_rate=0.01,
            window_seconds=60,
            wait_seconds=0,
            poll_seconds=1,
        )


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("minimum_samples", True),
        ("minimum_samples", 1.5),
        ("minimum_samples", float("nan")),
        ("window_seconds", 60.0),
        ("window_seconds", float("nan")),
        ("wait_seconds", True),
        ("wait_seconds", 1.5),
        ("wait_seconds", float("nan")),
        ("poll_seconds", True),
        ("poll_seconds", 1.5),
        ("poll_seconds", float("nan")),
    ],
)
def test_canary_policy_rejects_non_discrete_or_nonfinite_controls(field: str, bad: object) -> None:
    from scripts.gcp.canary_metrics import _validate_policy

    values = dict(
        project="abcdef",
        api_revision="a",
        web_revision="b",
        minimum_samples=20,
        maximum_error_rate=0.01,
        window_seconds=600,
        wait_seconds=240,
        poll_seconds=15,
    )
    values[field] = bad
    with pytest.raises(ValueError):
        _validate_policy(**values)


@pytest.mark.parametrize("bad_count", [True, 1.5, -1, "1.5", "NaN", "Infinity"])
def test_canary_request_counter_rejects_noncanonical_values(bad_count: object) -> None:
    payload = {
        "timeSeries": [
            {
                "metric": {"labels": {"response_code_class": "2xx"}},
                "points": [{"value": {"int64Value": bad_count}}],
            }
        ]
    }
    with pytest.raises(ValueError):
        summarize(payload, "korpus-api", "api-r2", 1, 0.01)
