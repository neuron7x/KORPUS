from __future__ import annotations

import html
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class ExtractedPage:
    page: int | None
    text: str


def _normalize(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_html(content: str) -> str:
    content = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", content, flags=re.I | re.S)
    content = re.sub(r"<[^>]+>", " ", content)
    return html.unescape(content)


def _ocr_pdf(content: bytes, languages: str) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    with tempfile.TemporaryDirectory(prefix="korpus-ocr-") as directory:
        root = Path(directory)
        pdf_path = root / "source.pdf"
        pdf_path.write_bytes(content)
        prefix = root / "page"
        subprocess.run(
            ["pdftoppm", "-png", "-r", "220", str(pdf_path), str(prefix)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=300,
        )
        for index, image_path in enumerate(sorted(root.glob("page-*.png")), start=1):
            completed = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", languages, "--psm", "6"],
                check=True,
                capture_output=True,
                timeout=120,
            )
            pages.append(ExtractedPage(page=index, text=_normalize(completed.stdout.decode("utf-8"))))
    return pages


def extract_pages(
    content: bytes,
    filename: str,
    mime_type: str,
    ocr_enabled: bool,
    ocr_languages: str,
) -> tuple[list[ExtractedPage], str]:
    suffix = Path(filename).suffix.casefold()
    if mime_type == "application/pdf" or suffix == ".pdf":
        reader = PdfReader(__import__("io").BytesIO(content))
        pages = [ExtractedPage(page=index, text=_normalize(page.extract_text() or "")) for index, page in enumerate(reader.pages, start=1)]
        printable = sum(len(page.text) for page in pages)
        if printable >= max(80, len(pages) * 30):
            return pages, "pdf_text"
        if not ocr_enabled:
            raise ValueError("PDF has insufficient embedded text and OCR is disabled")
        ocr_pages = _ocr_pdf(content, ocr_languages)
        if not any(page.text for page in ocr_pages):
            raise ValueError("OCR produced no text")
        return ocr_pages, "pdf_ocr"

    decoded = content.decode("utf-8-sig", errors="strict")
    if suffix == ".json" or mime_type == "application/json":
        decoded = json.dumps(json.loads(decoded), ensure_ascii=False, indent=2)
    elif suffix in {".html", ".htm"} or mime_type == "text/html":
        decoded = _strip_html(decoded)
    normalized = _normalize(decoded)
    if not normalized:
        raise ValueError("document contains no extractable text")
    return [ExtractedPage(page=None, text=normalized)], "plain_text"


def make_spans(
    pages: list[ExtractedPage],
    max_chars: int = 1400,
    overlap_chars: int = 180,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    ordinal = 0
    for page in pages:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", page.text) if part.strip()]
        buffer = ""
        for paragraph in paragraphs:
            if len(buffer) + len(paragraph) + 2 <= max_chars:
                buffer = f"{buffer}\n\n{paragraph}".strip()
                continue
            if buffer:
                output.append({"ordinal": ordinal, "page": page.page, "section": None, "text": buffer})
                ordinal += 1
                buffer = f"{buffer[-overlap_chars:]} {paragraph}".strip()
            else:
                for start in range(0, len(paragraph), max_chars - overlap_chars):
                    chunk = paragraph[start : start + max_chars].strip()
                    if chunk:
                        output.append({"ordinal": ordinal, "page": page.page, "section": None, "text": chunk})
                        ordinal += 1
                buffer = ""
        if buffer:
            output.append({"ordinal": ordinal, "page": page.page, "section": None, "text": buffer})
            ordinal += 1
    if not output:
        raise ValueError("document yielded no evidence spans")
    return output
