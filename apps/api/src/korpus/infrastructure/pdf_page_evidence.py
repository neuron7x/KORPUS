"""Identify pages whose visible raster content is absent from embedded text."""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from korpus.domain.models import ExtractedPage

_IMAGE_PAINT = frozenset({b"Do", b"INLINE IMAGE"})
_VISIBLE_PAINT = _IMAGE_PAINT | frozenset(
    {b"Tj", b"TJ", b"'", b'"', b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"sh"}
)


def remaining_time(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("extraction time budget exceeded")
    return remaining


def page_requires_ocr(page: Any, text: str) -> bool:
    """A text header cannot certify image contents on the rest of its page.

    A page without painting operations is genuinely blank for this text extractor.
    This does not claim interpretation of diagrams: visible content yielding no OCR
    text is refused rather than silently omitted.
    """
    content = page.get_contents()
    if content is None:
        return False
    operators = {operator for _operands, operator in content.operations}
    return bool(operators & _IMAGE_PAINT) or (not text and bool(operators & _VISIBLE_PAINT))


def required_pages(
    sources: Iterable[Any], pages: list[ExtractedPage], deadline: float
) -> tuple[int, ...]:
    required: list[int] = []
    for index, (source, extracted) in enumerate(zip(sources, pages, strict=True), start=1):
        remaining_time(deadline)
        if page_requires_ocr(source, extracted.text):
            required.append(index)
        remaining_time(deadline)
    return tuple(required)


def preserve_embedded_text(embedded: str, recognized: str, page: int) -> None:
    """OCR must not silently replace already known text with a weaker reading."""
    if not recognized.strip():
        raise ValueError(f"OCR produced no text for PDF page {page}")
    if " ".join(embedded.split()) not in " ".join(recognized.split()):
        raise ValueError(f"OCR did not preserve embedded text on PDF page {page}")
    if embedded and " ".join(embedded.split()) == " ".join(recognized.split()):
        raise ValueError(f"OCR added no text for incomplete PDF page {page}")
