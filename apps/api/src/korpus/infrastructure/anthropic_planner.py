"""A query planner backed by the Messages API. It suggests searches and nothing else.

Kept in `infrastructure` because it is a network call to a third party, and behind
`QueryPlanner` because the application must not know that a model exists. What it returns
passes `admissible_variant` before anything is searched — the adapter is not trusted to
have obeyed its own prompt, and a provider that started returning prose, or an answer
built to look like one, would produce refusals rather than text.

Two operational facts stated where an operator will read them:

  * Every question is sent to the provider. On an open corpus that is a decision already
    made; on a closed one the question itself is intelligence — who asked, about which
    system, when — and this must not be enabled.
  * One call per question, with a short timeout. A provider that is slow costs the
    reader nothing: `build_plan` degrades to the question as asked.
"""

from __future__ import annotations

from typing import Any

import httpx

from korpus.application.egress import EgressDenied, ModelEgressPolicy
from korpus.application.query_plan import PlannerUnavailable
from korpus.application.resilience import CircuitBreaker
from korpus.infrastructure.model_contract import (
    COMPOSE_INSTRUCTIONS,
    QUERY_REWRITE_INSTRUCTIONS,
    parse_composition,
    parse_query_variants,
)
from korpus.infrastructure.model_transport import guarded_json_post


def _refuse_if_egress_denied(policy: ModelEgressPolicy, base_url: str) -> None:
    """Turn an egress refusal into the failure the application already handles.

    `PlannerUnavailable` rather than letting `EgressDenied` escape: every call site
    already treats an unavailable model as "run without one" and records the reason in the
    audit chain, so a deployment that forbids egress degrades to the extractive path
    instead of returning 500 to a soldier. The reason string says which, so an operator
    reading the audit log can tell a policy refusal from a timeout.
    """
    try:
        policy.check(base_url)
    except EgressDenied as denial:
        raise PlannerUnavailable(f"model egress denied: {denial}") from denial


_SYSTEM = QUERY_REWRITE_INSTRUCTIONS

_MAX_OUTPUT_TOKENS = 300


class AnthropicQueryPlanner:
    """Suggests reformulations. Cannot contribute text to an answer by construction."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 6.0,
        egress: ModelEgressPolicy | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        #: Consulted before request construction; checking after response is already egress.
        self._egress = egress or ModelEgressPolicy()
        self._circuit = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=15.0)

    def variants(self, question: str, subjects: list[str]) -> list[str]:
        _refuse_if_egress_denied(self._egress, self._base_url)
        hint = f"\n\nРозділи корпусу: {', '.join(subjects[:40])}." if subjects else ""
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": _MAX_OUTPUT_TOKENS,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": f"Питання: {question}{hint}"}],
        }
        body = self._post(payload)
        return _parse(body)

    def _post(self, payload: dict[str, Any]) -> Any:
        return guarded_json_post(
            self._circuit,
            httpx.post,
            url=f"{self._base_url}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload=payload,
            timeout=self._timeout,
        )


def _parse(body: Any) -> list[str]:
    """The JSON array, or nothing. Provider prose is never partially trusted."""
    return parse_query_variants(_text_of(body))


_COMPOSE_SYSTEM = COMPOSE_INSTRUCTIONS


class AnthropicAnswerComposer:
    """Arranges retrieved sentences and proposes one opening line.

    Shares the planner's transport failure boundary. Third-party output is admitted,
    never trusted.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 8.0,
        egress: ModelEgressPolicy | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._egress = egress or ModelEgressPolicy()
        self._circuit = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=15.0)

    def compose(self, question: str, sentences: list[str]) -> tuple[str, list[str]]:
        _refuse_if_egress_denied(self._egress, self._base_url)
        numbered = "\n".join(f"{index}. {text}" for index, text in enumerate(sentences, 1))
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 1200,
            "system": _COMPOSE_SYSTEM,
            "messages": [
                {"role": "user", "content": f"Питання: {question}\n\nРечення:\n{numbered}"}
            ],
        }
        body = self._post(payload)
        return _parse_composition(body)

    def _post(self, payload: dict[str, Any]) -> Any:
        return guarded_json_post(
            self._circuit,
            httpx.post,
            url=f"{self._base_url}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload=payload,
            timeout=self._timeout,
        )


def _parse_composition(body: Any) -> tuple[str, list[str]]:
    """The object, or nothing. Half-understood output is worse than none."""
    return parse_composition(_text_of(body))


def _text_of(body: Any) -> str:
    blocks = body.get("content") if isinstance(body, dict) else None
    if not isinstance(blocks, list):
        return ""
    text = "".join(
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else ""
    return text
