"""OpenAI Responses API adapter for KORPUS's bounded model-assistance contract.

The adapter is intentionally thin. It can suggest retrieval phrases and arrange already
admitted extractive sentences; it cannot create evidence or bypass any downstream gate.
Every request sets ``store=false`` so the adapter does not opt into the Responses API's
default application-state retention. Egress policy is checked before a request is built.
"""

from __future__ import annotations

from typing import Any

import httpx

from korpus.application.egress import EgressDenied, ModelEgressPolicy
from korpus.application.query_plan import PlannerUnavailable
from korpus.infrastructure.model_contract import (
    COMPOSE_INSTRUCTIONS,
    QUERY_REWRITE_INSTRUCTIONS,
    parse_composition,
    parse_query_variants,
)

_MAX_QUERY_OUTPUT_TOKENS = 300
_MAX_COMPOSE_OUTPUT_TOKENS = 1200

_QUERY_FORMAT = {
    "type": "json_schema",
    "name": "korpus_query_variants",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"variants": {"type": "array", "items": {"type": "string"}}},
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
            "opening": {"type": "string"},
            "sentences": {"type": "array", "items": {"type": "string"}},
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


def _response_text(body: Any) -> str:
    """Extract text from the raw Responses API object, or return an empty string.

    ``output_text`` is accepted for compatibility with gateways that expose the SDK
    convenience field. The canonical raw shape is traversed through output/content.
    Unknown content types are ignored rather than guessed.
    """
    if not isinstance(body, dict):
        return ""
    direct = body.get("output_text")
    if isinstance(direct, str):
        return direct.strip()
    output = body.get("output")
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") not in {"output_text", "text"}:
                continue
            text = block.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks).strip()


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

    def variants(self, question: str, subjects: list[str]) -> list[str]:
        _refuse_if_egress_denied(self._egress, self._base_url)
        hint = f"\n\nРозділи корпусу: {', '.join(subjects[:40])}." if subjects else ""
        body = self._request(
            instructions=QUERY_REWRITE_INSTRUCTIONS,
            input_text=f"Питання: {question}{hint}",
            max_output_tokens=_MAX_QUERY_OUTPUT_TOKENS,
            text_format=_QUERY_FORMAT,
        )
        return parse_query_variants(_response_text(body))

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
            "input": input_text,
            "max_output_tokens": max_output_tokens,
            "store": False,
            "text": {"format": text_format},
        }
        try:
            response = httpx.post(
                f"{self._base_url}/v1/responses",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise PlannerUnavailable(f"{type(error).__name__}: {error}") from error


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
        return parse_composition(_response_text(body))
