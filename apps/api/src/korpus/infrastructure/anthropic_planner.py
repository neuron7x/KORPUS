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

import json
from typing import Any

import httpx

from korpus.application.query_plan import PlannerUnavailable

#: The vocabulary problem this exists for, stated as the task. The model is given the
#: corpus's own subject names so its guesses land in the language the documents use.
_SYSTEM = """Ти — переформулювач запитів до закритого корпусу українських військових
документів. Твоє єдине завдання: повернути короткі пошукові фрази, якими це саме питання
сформульоване в статутах, настановах і бойових документах.

Правила:
- Лише пошукові фрази, 2–6 слів, українською, у лексиці військових документів.
- Синоніми і статутні терміни: «обстріл» → «артилерійський наліт», «укриття», «щілина».
- Жодних пояснень, жодних речень, жодних відповідей на питання.
- Якщо питання вже сформульоване термінами корпусу — поверни порожній список.

Формат відповіді: JSON-масив рядків і нічого більше."""

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
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def variants(self, question: str, subjects: list[str]) -> list[str]:
        hint = (
            f"\n\nРозділи корпусу: {', '.join(subjects[:40])}." if subjects else ""
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": _MAX_OUTPUT_TOKENS,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": f"Питання: {question}{hint}"}],
        }
        try:
            response = httpx.post(
                f"{self._base_url}/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as error:
            # Wrapped here because this is the only layer that knows what an HTTP client
            # can do. The application is told the suggestion did not arrive, and by whom.
            raise PlannerUnavailable(f"{type(error).__name__}: {error}") from error
        return _parse(body)


def _parse(body: Any) -> list[str]:
    """The JSON array, or nothing.

    A provider answering in prose, in a code fence, or with an apology yields an empty
    list rather than a partially-understood one: half-parsed output is how a sentence
    ends up being searched for as a phrase and quietly narrows every result.
    """
    blocks = body.get("content") if isinstance(body, dict) else None
    if not isinstance(blocks, list):
        return []
    text = "".join(
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else ""
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]
