"""OpenAI Responses API adapter for KORPUS's bounded model-assistance contract.

The adapter is intentionally thin. It can suggest retrieval phrases and arrange already
admitted extractive sentences; it cannot create evidence or bypass any downstream gate.
Requests set ``store=false`` and pass egress policy before they are built.
"""

from __future__ import annotations

from typing import Any

import httpx

from korpus.application.egress import EgressDenied, ModelEgressPolicy
from korpus.application.query_plan import PlannerUnavailable
from korpus.application.resilience import CircuitBreaker
from korpus.infrastructure.model_contract import (
    COMPOSE_INSTRUCTIONS,
    MAX_COMPOSITION_OPENING_CHARS,
    MAX_COMPOSITION_SENTENCE_CHARS,
    MAX_COMPOSITION_SENTENCES,
    MAX_QUERY_VARIANT_CHARS,
    MAX_QUERY_VARIANTS,
    QUERY_REWRITE_INSTRUCTIONS,
    parse_composition,
    parse_query_variants,
)
from korpus.infrastructure.model_input import bounded_model_input
from korpus.infrastructure.model_transport import guarded_json_post
from korpus.infrastructure.openai_response import completed_response_text

_MAX_QUERY_OUTPUT_TOKENS = 300
_MAX_COMPOSE_OUTPUT_TOKENS = 1200

_QUERY_FORMAT = {
    "type": "json_schema",
    "name": "korpus_query_variants",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "variants": {
                "type": "array",
                "maxItems": MAX_QUERY_VARIANTS,
                "items": {"type": "string", "maxLength": MAX_QUERY_VARIANT_CHARS},
            }
        },
        "required": ["variants"],
        "additionalProperties": False,
    },
}
_COMPOSE_FORMAT = {
    "type": "json_schema",
    "name": "korpus_answer_composition",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "opening": {"type": "string", "maxLength": MAX_COMPOSITION_OPENING_CHARS},
            "sentences": {
                "type": "array",
                "maxItems": MAX_COMPOSITION_SENTENCES,
                "items": {"type": "string", "maxLength": MAX_COMPOSITION_SENTENCE_CHARS},
            },
        },
        "required": ["opening", "sentences"],
        "additionalProperties": False,
    },
}


def _refuse_if_egress_denied(policy: ModelEgressPolicy, base_url: str) -> None:
    try:
        policy.check(base_url)
    except EgressDenied as denial:
        raise PlannerUnavailable(f"model egress denied: {denial}") from denial


class OpenAIQueryPlanner:
    """Suggest retrieval variants through the Responses API."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        base_url: str = "https://api.openai.com",
        timeout_seconds: float = 6.0,
        egress: ModelEgressPolicy | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._egress = egress or ModelEgressPolicy()
        self._circuit = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=15.0)

    def variants(self, question: str, subjects: list[str]) -> list[str]:
        _refuse_if_egress_denied(self._egress, self._base_url)
        hint = f"\n\nРозділи корпусу: {', '.join(subjects[:40])}." if subjects else ""
        body = self._request(
            instructions=QUERY_REWRITE_INSTRUCTIONS,
            input_text=f"Питання: {question}{hint}",
            max_output_tokens=_MAX_QUERY_OUTPUT_TOKENS,
            text_format=_QUERY_FORMAT,
        )
        return parse_query_variants(completed_response_text(body))

    def _request(
        self,
        *,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
        text_format: dict[str, Any],
    ) -> Any:
        payload = {
            "model": self._model,
            "instructions": instructions,
            "input": bounded_model_input(input_text),
            "max_output_tokens": max_output_tokens,
            "store": False,
            "tools": [],
            "parallel_tool_calls": False,
            "truncation": "disabled",
            "text": {"format": text_format},
        }
        return guarded_json_post(
            self._circuit,
            httpx.post,
            url=f"{self._base_url}/v1/responses",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
            timeout=self._timeout,
        )


class OpenAIAnswerComposer(OpenAIQueryPlanner):
    """Arrange extractive claims; downstream admission still decides what may render."""

    def compose(self, question: str, sentences: list[str]) -> tuple[str, list[str]]:
        _refuse_if_egress_denied(self._egress, self._base_url)
        numbered = "\n".join(f"{index}. {text}" for index, text in enumerate(sentences, 1))
        body = self._request(
            instructions=COMPOSE_INSTRUCTIONS,
            input_text=f"Питання: {question}\n\nРечення:\n{numbered}",
            max_output_tokens=_MAX_COMPOSE_OUTPUT_TOKENS,
            text_format=_COMPOSE_FORMAT,
        )
        return parse_composition(completed_response_text(body))
