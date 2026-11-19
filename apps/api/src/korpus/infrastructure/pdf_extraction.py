from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import LimitReachedError, PdfReadError

from korpus.domain.models import ExtractedPage

Normalize = Callable[[str], str]


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("extraction time budget exceeded")
    return remaining


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
            pages.append(ExtractedPage(page=index, text=normalize(page.extract_text() or "")))
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
) -> tuple[list[ExtractedPage], bool, bool]:
    try:
        reader, owner_restricted, lenient = _open_pdf(path, max_pdf_pages, reader_factory)
        return _embedded_pages(reader, deadline, normalize), owner_restricted, lenient
    except LimitReachedError as exc:
        # Convert outside the lenient-reader fallback: resource refusal is terminal.
        raise ValueError("PDF parser resource limit exceeded") from exc


def _ocr_pages(
    path: Path,
    languages: str,
    deadline: float,
    max_pages: int,
    normalize: Normalize,
) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    with tempfile.TemporaryDirectory(prefix="korpus-ocr-") as directory:
        root = Path(directory)
        prefix = root / "page"
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "220",
                "-f",
                "1",
                "-l",
                str(max_pages),
                str(path),
                str(prefix),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_remaining(deadline),
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
        )
        images = sorted(root.glob("page-*.png"))
        if len(images) > max_pages:
            raise ValueError("OCR renderer exceeded page limit")
        for index, image_path in enumerate(images, start=1):
            completed = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", languages, "--psm", "6"],
                check=True,
                capture_output=True,
                timeout=_remaining(deadline),
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
            )
            pages.append(
                ExtractedPage(page=index, text=normalize(completed.stdout.decode("utf-8")))
            )
    return pages


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
    pages, owner_restricted, lenient = _read_embedded_pdf(
        path, max_pdf_pages, reader_factory, deadline, normalize
    )
    if sum(len(page.text) for page in pages) >= max(80, len(pages) * 30):
        mode = "pdf_text_owner_restricted" if owner_restricted else "pdf_text"
        return pages, f"{mode}_lenient" if lenient else mode
    if not ocr_enabled:
        raise ValueError("PDF has insufficient embedded text and OCR is disabled")
    try:
        pages = _ocr_pages(path, ocr_languages, deadline, max_pdf_pages, normalize)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("OCR execution failed") from exc
    if not any(page.text for page in pages):
        raise ValueError("OCR produced no text")
    return pages, "pdf_ocr_owner_restricted" if owner_restricted else "pdf_ocr"
