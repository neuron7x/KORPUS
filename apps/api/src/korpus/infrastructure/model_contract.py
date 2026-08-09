"""Provider-independent contract for optional language-model assistance.

The model has two bounded jobs in KORPUS: suggest search phrases and arrange already
admitted extractive sentences. Provider adapters share these instructions and strict
parsers so switching vendors cannot silently change the authority granted to a model.
"""

from __future__ import annotations

import json
from typing import Any

QUERY_REWRITE_INSTRUCTIONS = """Ти — переформулювач запитів до закритого корпусу українських військових
документів. Твоє єдине завдання: повернути короткі пошукові фрази, якими це саме питання
сформульоване в статутах, настановах і бойових документах.

Правила:
- Лише пошукові фрази, 2–6 слів, українською, у лексиці військових документів.
- Синоніми і статутні терміни: «обстріл» → «артилерійський наліт», «укриття», «щілина».
- Жодних пояснень, жодних речень, жодних відповідей на питання.
- Якщо питання вже сформульоване термінами корпусу — поверни порожній список.

Формат відповіді — JSON і нічого більше:
{"variants": ["...", "..."]}"""

COMPOSE_INSTRUCTIONS = """Ти впорядковуєш готові речення з військових документів. Ти НЕ пишеш
відповідь і НЕ додаєш фактів.

Отримуєш питання і список речень, узятих дослівно з документів.

Робиш дві речі:
1. Розташовуєш речення в порядку, у якому їх слід читати. Усі речення, жодного зайвого,
   жодного пропущеного.
2. Пишеш один рядок вступу — до 15 слів, який каже, про що ці речення.

Правила вступу, за якими його перевірять машинно:
- жодних цифр;
- жодних заперечень («не», «без», «заборонено»);
- кожне змістовне слово мусить уже бути в наданих реченнях.

Формат відповіді — JSON і нічого більше:
{"opening": "...", "sentences": ["...", "..."]}"""


def strip_code_fence(text: str) -> str:
    value = text.strip()
    if not value.startswith("```"):
        return value
    value = value.strip("`")
    return value.split("\n", 1)[1] if "\n" in value else ""


def parse_query_variants(text: str) -> list[str]:
    """Parse exactly one JSON array; malformed provider output contributes nothing."""
    value = strip_code_fence(text)
    start, end = value.find("["), value.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        parsed = json.loads(value[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]


def parse_composition(text: str) -> tuple[str, list[str]]:
    """Parse one composition object; partial understanding is a refusal."""
    value = strip_code_fence(text)
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        return "", []
    try:
        parsed: Any = json.loads(value[start : end + 1])
    except json.JSONDecodeError:
        return "", []
    if not isinstance(parsed, dict):
        return "", []
    sentences = parsed.get("sentences")
    return (
        str(parsed.get("opening", "")),
        [item for item in sentences if isinstance(item, str)] if isinstance(sentences, list)
        else [],
    )
