from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import LimitReachedError, PdfReadError

from korpus.domain.models import ExtractedPage
from korpus.infrastructure.pdf_ocr import ocr_pages as _ocr_pages
from korpus.infrastructure.pdf_page_evidence import preserve_embedded_text, required_pages
from korpus.infrastructure.pdf_page_evidence import remaining_time as _remaining

Normalize = Callable[[str], str]


def _open_strict(
    path: Path, max_pdf_pages: int, reader_factory: Callable[..., Any], *, strict: bool
) -> tuple[PdfReader, bool]:
    try:
        reader = reader_factory(str(path), strict=strict)
    except (OSError, ValueError, TypeError, PdfReadError) as exc:
        raise ValueError("malformed PDF") from exc
    owner_restricted = bool(reader.is_encrypted)
    if owner_restricted:
        try:
            opened = reader.decrypt("")
        except (NotImplementedError, ValueError, PdfReadError) as exc:
            raise ValueError("encrypted PDF uses an unsupported algorithm") from exc
        if not opened:
            raise ValueError("encrypted PDF requires a password that was not supplied")
    try:
        page_count = len(reader.pages)
    except (KeyError, ValueError, TypeError, RecursionError, PdfReadError) as exc:
        raise ValueError("malformed PDF page tree") from exc
    if page_count > max_pdf_pages:
        raise ValueError("PDF page count exceeds configured limit")
    return reader, owner_restricted


def _open_pdf(
    path: Path, max_pdf_pages: int, reader_factory: Callable[..., Any]
) -> tuple[PdfReader, bool, bool]:
    """Read strictly first; record lenient recovery without relaxing page limits."""
    try:
        reader, owner_restricted = _open_strict(path, max_pdf_pages, reader_factory, strict=True)
    except ValueError as strict_error:
        if "page count exceeds" in str(strict_error):
            raise
        reader, owner_restricted = _open_strict(path, max_pdf_pages, reader_factory, strict=False)
        return reader, owner_restricted, True
    return reader, owner_restricted, False


def _embedded_pages(
    reader: PdfReader, deadline: float, normalize: Normalize
) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    try:
        for index, page in enumerate(reader.pages, start=1):
            _remaining(deadline)
            text = normalize(page.extract_text() or "")
            pages.append(ExtractedPage(page=index, text=text))
            _remaining(deadline)
    except ValueError:
        raise
    except (KeyError, TypeError, RecursionError, PdfReadError) as exc:
        raise ValueError("PDF text extraction failed") from exc
    return pages


def _read_embedded_pdf(
    path: Path,
    max_pdf_pages: int,
    reader_factory: Callable[..., Any],
    deadline: float,
    normalize: Normalize,
) -> tuple[list[ExtractedPage], bool, bool, tuple[int, ...]]:
    try:
        reader, owner_restricted, lenient = _open_pdf(path, max_pdf_pages, reader_factory)
        pages = _embedded_pages(reader, deadline, normalize)
        required = required_pages(reader.pages, pages, deadline)
        return pages, owner_restricted, lenient, required
    except LimitReachedError as exc:
        # Convert outside the lenient-reader fallback: resource refusal is terminal.
        raise ValueError("PDF parser resource limit exceeded") from exc
    except (KeyError, TypeError, RecursionError, PdfReadError) as exc:
        raise ValueError("PDF page inspection failed") from exc


def _replace_ocr_pages(
    pages: list[ExtractedPage], recognized: list[ExtractedPage], required: tuple[int, ...]
) -> None:
    if not recognized:
        raise ValueError("OCR produced no text")
    if tuple(page.page for page in recognized) != required:
        raise ValueError("OCR returned an incomplete page inventory")
    for page in recognized:
        assert page.page is not None
        original = pages[page.page - 1]
        preserve_embedded_text(original.text, page.text, page.page)
        pages[page.page - 1] = page


def _method(required: tuple[int, ...], count: int, owner_restricted: bool, lenient: bool) -> str:
    method = "pdf_ocr" if required else "pdf_text"
    if required and len(required) < count:
        method += "_mixed"
    if owner_restricted:
        method += "_owner_restricted"
    return f"{method}_lenient" if lenient else method


def extract_pdf_pages(
    path: Path,
    ocr_enabled: bool,
    ocr_languages: str,
    normalize: Normalize,
    *,
    max_pdf_pages: int,
    ocr_total_timeout_seconds: int,
    reader_factory: Callable[..., Any] = PdfReader,
) -> tuple[list[ExtractedPage], str]:
    deadline = time.monotonic() + ocr_total_timeout_seconds
    pages, owner_restricted, lenient, required = _read_embedded_pdf(
        path, max_pdf_pages, reader_factory, deadline, normalize
    )
    if required and not ocr_enabled:
        raise ValueError(f"PDF pages {required} require OCR and OCR is disabled")
    if required:
        try:
            recognized = _ocr_pages(
                path, ocr_languages, deadline, max_pdf_pages, normalize, page_numbers=required
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("OCR execution failed") from exc
        _replace_ocr_pages(pages, recognized, required)
    if not any(page.text for page in pages):
        raise ValueError("PDF contains no extractable text")
    return pages, _method(required, len(pages), owner_restricted, lenient)
