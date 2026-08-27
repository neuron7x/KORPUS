from __future__ import annotations

import httpx
import pytest
from korpus.application.query_plan import PlannerUnavailable
from korpus.infrastructure import anthropic_planner
from korpus.infrastructure.anthropic_planner import (
    AnthropicAnswerComposer,
    AnthropicQueryPlanner,
    _text_of,
)


class _Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.body


def test_query_planner_transport_contract_covers_subject_and_no_subject_paths(monkeypatch) -> None:
    payloads = []

    def post(*_args, **kwargs):
        payloads.append(kwargs["json"])
        return _Response({"content": [{"type": "text", "text": '{"variants":["бойове укриття"]}'}]})

    monkeypatch.setattr(anthropic_planner.httpx, "post", post)
    planner = AnthropicQueryPlanner("key", model="m")
    assert planner.variants("питання", []) == ["бойове укриття"]
    assert planner.variants("питання", ["alpha", "beta"]) == ["бойове укриття"]
    assert "Розділи корпусу" not in payloads[0]["messages"][0]["content"]
    assert "alpha, beta" in payloads[1]["messages"][0]["content"]


def test_answer_composer_transport_contract(monkeypatch) -> None:
    def post(*_args, **_kwargs):
        return _Response(
            {"content": [{"type": "text", "text": '{"opening":"Вступ","sentences":["A","B"]}'}]}
        )

    monkeypatch.setattr(anthropic_planner.httpx, "post", post)
    composer = AnthropicAnswerComposer("key", model="m")
    assert composer.compose("питання", ["A", "B"]) == ("Вступ", ["A", "B"])


def test_http_failures_are_normalized_to_planner_unavailable(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(anthropic_planner.httpx, "post", fail)
    with pytest.raises(PlannerUnavailable, match="ConnectError"):
        AnthropicQueryPlanner("key", model="m").variants("питання", [])
    with pytest.raises(PlannerUnavailable, match="ConnectError"):
        AnthropicAnswerComposer("key", model="m").compose("питання", ["A"])


def test_oversized_material_is_refused_before_anthropic_transport(monkeypatch) -> None:
    monkeypatch.setattr(
        anthropic_planner.httpx,
        "post",
        lambda *args, **kwargs: pytest.fail("oversized material reached the provider"),
    )
    with pytest.raises(ValueError, match="model input exceeds"):
        AnthropicQueryPlanner("key", model="m").variants("я" * 70_000, [])
    with pytest.raises(ValueError, match="model input exceeds"):
        AnthropicAnswerComposer("key", model="m").compose("питання", ["д" * 70_000])


def test_repeated_anthropic_failure_opens_circuit(monkeypatch) -> None:
    calls = 0

    def fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(anthropic_planner.httpx, "post", fail)
    planner = AnthropicQueryPlanner("key", model="m")

    failures = []
    for _ in range(4):
        with pytest.raises(PlannerUnavailable) as caught:
            planner.variants("питання", [])
        failures.append(str(caught.value))

    assert calls == 3
    assert "CircuitOpenError" in failures[-1]


def test_text_extraction_refuses_wrong_shapes_and_normalizes_fences() -> None:
    assert _text_of(None) == ""
    assert _text_of({"content": "not-a-list"}) == ""
    assert (
        _text_of(
            {"content": [None, {"type": "image", "text": "x"}, {"type": "text", "text": " y "}]}
        )
        == "y"
    )
    assert _text_of({"content": [{"type": "text", "text": '```json\n["x"]```'}]}) == '["x"]'
    assert _text_of({"content": [{"type": "text", "text": "```"}]}) == ""
