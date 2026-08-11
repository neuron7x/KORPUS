from __future__ import annotations

import io
import json
import urllib.error

import pytest

from scripts import load_probe


def test_outcome_keeps_typed_refusal_reasons_separate_from_http_status() -> None:
    outcome = load_probe.Outcome()
    outcome.record(0.1, "503", refusal_reason="subject_share_exhausted")
    outcome.record(0.2, "503", refusal_reason="global_capacity_exhausted")
    outcome.record(0.3, "503", refusal_reason="subject_share_exhausted")

    summary = outcome.summary()

    assert summary["statuses"] == {"503": 3}
    assert summary["refusal_reasons"] == {
        "subject_share_exhausted": 2,
        "global_capacity_exhausted": 1,
    }


def test_http_error_body_preserves_the_server_admission_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"detail": {"reason": "subject_share_exhausted"}}).encode()

    def refuse(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.HTTPError(
            "http://example.invalid/v1/answers",
            503,
            "Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(body),
        )

    monkeypatch.setattr(load_probe.urllib.request, "urlopen", refuse)

    _latency, status, decision, reason = load_probe._ask(
        "http://example.invalid", "question", 0.1
    )

    assert status == "503"
    assert decision == ""
    assert reason == "subject_share_exhausted"


def test_malformed_error_body_is_not_silently_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.HTTPError(
            "http://example.invalid/v1/answers",
            503,
            "Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(b"not-json"),
        )

    monkeypatch.setattr(load_probe.urllib.request, "urlopen", refuse)

    assert load_probe._ask("http://example.invalid", "question", 0.1)[3] == "malformed_error_body"
