"""ACT-006: OpenAI is an optional transport, never an evidence authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from korpus.api.dependencies import build_answer_composer, build_query_planner
from korpus.application.egress import EgressPosture, ModelEgressPolicy
from korpus.application.query_plan import PlannerUnavailable
from korpus.config import Settings
from korpus.infrastructure.openai_planner import OpenAIAnswerComposer, OpenAIQueryPlanner
from korpus.model_settings import resolved_model_api_key, resolved_model_base_url


class _Response:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._body


def _responses_body(text: str) -> dict[str, Any]:
    return {
        "id": "resp_test",
        "status": "completed",
        "error": None,
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    }


def test_openai_planner_uses_responses_api_store_false_and_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def post(url: str, **kwargs: Any) -> _Response:
        seen.update(url=url, **kwargs)
        return _Response(_responses_body('["артилерійський наліт", "щілина укриття"]'))

    monkeypatch.setattr("korpus.infrastructure.openai_planner.httpx.post", post)
    planner = OpenAIQueryPlanner("secret", model="model-under-test")

    assert planner.variants("що робити при обстрілі", ["тактика"]) == [
        "артилерійський наліт",
        "щілина укриття",
    ]
    assert seen["url"] == "https://api.openai.com/v1/responses"
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert seen["json"]["store"] is False
    assert seen["json"]["tools"] == []
    assert seen["json"]["parallel_tool_calls"] is False
    assert seen["json"]["truncation"] == "disabled"
    assert seen["json"]["model"] == "model-under-test"
    assert seen["json"]["text"]["format"]["type"] == "json_schema"
    assert seen["json"]["text"]["format"]["strict"] is True
    assert seen["json"]["text"]["format"]["name"] == "korpus_query_variants"
    assert "що робити при обстрілі" in seen["json"]["input"]
    assert "тактика" in seen["json"]["input"]


def test_openai_composer_uses_same_contract_and_store_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}
    sentences = ["Особовий склад займає укриття.", "Рух виконується за командою."]
    body = (
        '{"opening":"Особовий склад займає укриття","sentences":'
        '["Особовий склад займає укриття.","Рух виконується за командою."]}'
    )

    def post(url: str, **kwargs: Any) -> _Response:
        seen.update(url=url, **kwargs)
        return _Response(_responses_body(body))

    monkeypatch.setattr("korpus.infrastructure.openai_planner.httpx.post", post)
    composer = OpenAIAnswerComposer("secret", model="model-under-test")

    opening, ordered = composer.compose("де бути", sentences)
    assert opening == "Особовий склад займає укриття"
    assert ordered == sentences
    assert seen["json"]["store"] is False
    assert seen["json"]["max_output_tokens"] == 1200
    assert seen["json"]["text"]["format"]["name"] == "korpus_answer_composition"
    assert seen["json"]["text"]["format"]["strict"] is True


def test_openai_malformed_output_contributes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "korpus.infrastructure.openai_planner.httpx.post",
        lambda *args, **kwargs: _Response(_responses_body("I cannot comply")),
    )
    planner = OpenAIQueryPlanner("secret", model="model-under-test")
    composer = OpenAIAnswerComposer("secret", model="model-under-test")

    assert planner.variants("питання", []) == []
    assert composer.compose("питання", ["готове речення"])[0:2] == ("", [])


@pytest.mark.parametrize("status", ["failed", "incomplete", "in_progress", "queued"])
def test_openai_non_completed_response_contributes_nothing(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    body = _responses_body('{"variants":["неповний результат"]}')
    body["status"] = status
    monkeypatch.setattr(
        "korpus.infrastructure.openai_planner.httpx.post",
        lambda *args, **kwargs: _Response(body),
    )

    assert OpenAIQueryPlanner("secret", model="model-under-test").variants("питання", []) == []


def test_openai_completed_response_with_error_contributes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _responses_body('{"variants":["помилковий результат"]}')
    body["error"] = {"code": "provider_error", "message": "generation failed"}
    monkeypatch.setattr(
        "korpus.infrastructure.openai_planner.httpx.post",
        lambda *args, **kwargs: _Response(body),
    )

    assert OpenAIQueryPlanner("secret", model="model-under-test").variants("питання", []) == []


def test_repeated_provider_failure_opens_process_scoped_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def unavailable(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr("korpus.infrastructure.openai_planner.httpx.post", unavailable)
    planner = OpenAIQueryPlanner("secret", model="model-under-test")

    failures: list[str] = []
    for _ in range(4):
        with pytest.raises(PlannerUnavailable) as caught:
            planner.variants("питання", [])
        failures.append(str(caught.value))

    assert calls == 3
    assert "CircuitOpenError" in failures[-1]


def test_model_disabled_refuses_before_openai_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("transport must not be reached")

    monkeypatch.setattr("korpus.infrastructure.openai_planner.httpx.post", forbidden)
    policy = ModelEgressPolicy(EgressPosture.MODEL_DISABLED)
    planner = OpenAIQueryPlanner("secret", model="m", egress=policy)

    with pytest.raises(PlannerUnavailable, match="model egress denied"):
        planner.variants("питання", [])


def test_composition_root_selects_openai_without_leaking_provider_into_application() -> None:
    settings = Settings(
        environment="test",
        query_planner_enabled=True,
        answer_composer_enabled=True,
        query_planner_provider="openai",
        query_planner_api_key="secret",
        query_planner_model="model-under-test",
    )

    assert isinstance(build_query_planner(settings), OpenAIQueryPlanner)
    assert isinstance(build_answer_composer(settings), OpenAIAnswerComposer)
    assert resolved_model_base_url(settings) == "https://api.openai.com"


def test_model_api_key_can_come_from_a_secret_file(tmp_path: Path) -> None:
    secret = tmp_path / "model-key"
    secret.write_text("from-file\n", encoding="utf-8")
    settings = Settings(
        environment="test",
        query_planner_provider="openai",
        query_planner_api_key_file=secret,
        query_planner_model="model-under-test",
    )

    assert resolved_model_api_key(settings) == "from-file"


def test_openai_provider_requires_explicit_model_name() -> None:
    with pytest.raises(ValueError, match="explicit OpenAI model"):
        Settings(
            environment="test",
            query_planner_provider="openai",
            query_planner_model="claude-sonnet-5",
        )


def test_new_deployment_defaults_to_openai_sol_but_keeps_model_calls_disabled() -> None:
    settings = Settings(environment="test")
    assert settings.query_planner_provider == "openai"
    assert settings.query_planner_model == "gpt-5.6-sol"
    assert settings.query_planner_enabled is False
    assert settings.answer_composer_enabled is False
