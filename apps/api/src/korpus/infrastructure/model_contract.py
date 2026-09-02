"""Provider-independent contract for optional language-model assistance.

The model has two bounded jobs in KORPUS: suggest search phrases and arrange already
admitted extractive sentences. Provider adapters share these instructions and strict
parsers so switching vendors cannot silently change the authority granted to a model.

ВИМІРЯНО 02.09.2026 на qwen2.5:3b справжніми промтами й парсерами — тести перевіряють
лише ПАРСЕР канонсервованими рядками й про промт не кажуть нічого. Rewrite: 0 придатних
варіантів із 40 питань; абляція однієї змінної називає причину — правило «поверни
порожній список» модель бере як вихід і бере завжди (0/12 із ним, 7/12 без). Знімати
його не можна без заміни: без нього та сама модель вигадує терміни й раз віддала
літерал «...» із прикладу формату. Compose: допущено 0 з 23 справжніх витягів, p50
6.65 с при дедлайні 10 с (5 із 23 не встигають), сторож при цьому живий — 4 підробки з
4 відхилено. Числа про 3B; переноситься лише висновок про ФОРМУ промту.
"""

from __future__ import annotations

import json
from typing import Any

MAX_QUERY_VARIANTS = 4
MAX_QUERY_VARIANT_CHARS = 120
MAX_COMPOSITION_SENTENCES = 4
MAX_COMPOSITION_SENTENCE_CHARS = 2000
MAX_COMPOSITION_OPENING_CHARS = 300

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
    if len(parsed) > MAX_QUERY_VARIANTS or any(
        not isinstance(item, str) or len(item) > MAX_QUERY_VARIANT_CHARS for item in parsed
    ):
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
    # Braces make the successfully decoded slice an object; its fields remain untrusted.
    opening = parsed.get("opening")
    sentences = parsed.get("sentences")
    items = sentences if isinstance(sentences, list) else []
    invalid = (
        not isinstance(opening, str)
        or len(opening) > MAX_COMPOSITION_OPENING_CHARS
        or not isinstance(sentences, list)
        or len(sentences) > MAX_COMPOSITION_SENTENCES
        or any(
            not isinstance(item, str) or len(item) > MAX_COMPOSITION_SENTENCE_CHARS
            for item in items
        )
    )
    return ("", []) if invalid else (opening, items)
