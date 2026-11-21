"""Identify incomplete PDF text and refuse unsupported annotation appearances."""

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
    if (remaining := deadline - time.monotonic()) <= 0:
        raise ValueError("extraction time budget exceeded")
    return remaining


def _refuse_annotation_appearances(page: Any) -> None:
    annotations = page.get("/Annots", ())
    if any(annotation.get_object().get("/AP") is not None for annotation in annotations):
        raise ValueError("PDF annotation appearance is unsupported")


def page_requires_ocr(page: Any, text: str) -> bool:
    _refuse_annotation_appearances(page)
    content = page.get_contents()
    if content is None:
        return False
    operators = {operator for _operands, operator in content.operations}
    return bool(operators & (_IMAGE_PAINT if text else _VISIBLE_PAINT))


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
