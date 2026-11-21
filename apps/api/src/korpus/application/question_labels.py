"""Conservative identity rules for single-letter names that also act as function words."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection

from korpus.application.retrieval_math import STOP_WORDS

FUNCTION_WORDS = STOP_WORDS | {
    "і",
    "й",
    "у",
    "в",
    "з",
    "із",
    "зі",
    "щодо",
    "of",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "to",
    "on",
    "in",
    "at",
    "by",
    "about",
    "what",
    "which",
}
QUOTED_NAMES = re.compile(r'«([^»]+)»|“([^”]+)”|"([^"\n]+)"')
_TRAILING_LABEL = re.compile(r"(?<!\w)([^\W\d_])[\s?.!,;:]*\Z")


def normalize_question(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold().replace("’", "'")


def ambiguous_trailing_label(question: str, function_words: Collection[str]) -> bool:
    candidate = _TRAILING_LABEL.search(question)
    return bool(
        candidate and candidate[1].isupper() and normalize_question(candidate[1]) in function_words
    )


def quoted_label_met(label: str, text: str) -> bool:
    return any(
        normalize_question(value) == label
        for match in QUOTED_NAMES.finditer(text)
        for value in match.groups()
        if value is not None
    )
