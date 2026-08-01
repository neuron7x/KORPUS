from __future__ import annotations

import re
from dataclasses import dataclass

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REPEATED_SYMBOL = re.compile(r"([^\w\s])\1{19,}", re.UNICODE)
_PATHOLOGICAL_TOKEN = re.compile(r"\S{121,}")


@dataclass(frozen=True)
class ExtractionQuality:
    text_chars: int
    alnum_ratio: float
    replacement_ratio: float
    flags: frozenset[str]


def assess_extraction_quality(text: str) -> ExtractionQuality:
    """Return deterministic parser/OCR warning predicates, not a confidence score."""
    total = len(text)
    denominator = max(total, 1)
    alnum_ratio = sum(char.isalnum() for char in text) / denominator
    replacement_ratio = text.count("\ufffd") / denominator
    flags: set[str] = set()
    if total < 20:
        flags.add("insufficient_text")
    if replacement_ratio > 0.001:
        flags.add("replacement_characters")
    if _CONTROL.search(text):
        flags.add("control_characters")
    if total >= 20 and alnum_ratio < 0.35:
        flags.add("low_alphanumeric_density")
    if _REPEATED_SYMBOL.search(text):
        flags.add("repeated_symbol_run")
    if _PATHOLOGICAL_TOKEN.search(text):
        flags.add("pathological_token")
    return ExtractionQuality(
        text_chars=total,
        alnum_ratio=round(alnum_ratio, 6),
        replacement_ratio=round(replacement_ratio, 6),
        flags=frozenset(flags),
    )
