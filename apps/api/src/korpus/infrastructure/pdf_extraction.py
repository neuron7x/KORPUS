from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from korpus.domain.models import ExtractedPage

Normalize = Callable[[str], str]


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("extraction time budget exceeded")
    return remaining


def _open_pdf(
    path: Path, max_pdf_pages: int, reader_factory: Callable[..., Any]
) -> tuple[PdfReader, bool]:
    try:
        reader = reader_factory(str(path), strict=True)
    except (OSError, ValueError, TypeError, PdfReadError) as exc:
        raise ValueError("malformed PDF") from exc
    owner_restricted = False
    if reader.is_encrypted:
        try:
            opened = reader.decrypt("")
        except (NotImplementedError, ValueError, PdfReadError) as exc:
            raise ValueError("encrypted PDF uses an unsupported algorithm") from exc
        if not opened:
            raise ValueError("encrypted PDF requires a password that was not supplied")
        owner_restricted = True
    try:
        page_count = len(reader.pages)
    except (KeyError, ValueError, TypeError, RecursionError, PdfReadError) as exc:
        raise ValueError("malformed PDF page tree") from exc
    if page_count > max_pdf_pages:
        raise ValueError("PDF page count exceeds configured limit")
    return reader, owner_restricted


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
    reader, owner_restricted = _open_pdf(path, max_pdf_pages, reader_factory)
    pages = _embedded_pages(reader, deadline, normalize)
    if sum(len(page.text) for page in pages) >= max(80, len(pages) * 30):
        return pages, "pdf_text_owner_restricted" if owner_restricted else "pdf_text"
    if not ocr_enabled:
        raise ValueError("PDF has insufficient embedded text and OCR is disabled")
    try:
        pages = _ocr_pages(path, ocr_languages, deadline, max_pdf_pages, normalize)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("OCR execution failed") from exc
    if not any(page.text for page in pages):
        raise ValueError("OCR produced no text")
    return pages, "pdf_ocr_owner_restricted" if owner_restricted else "pdf_ocr"
