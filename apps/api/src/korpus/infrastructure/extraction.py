from __future__ import annotations

import html
import io
import json
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

SUPPORTED_SUFFIXES = {".txt", ".md", ".json", ".html", ".htm", ".pdf"}
SUPPORTED_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "application/json",
    "text/html",
    "application/pdf",
}


@dataclass(frozen=True)
class ExtractedPage:
    page: int | None
    text: str


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_html(content: str) -> str:
    content = re.sub(r"<(script|style|iframe|object)[^>]*>.*?</\1>", " ", content, flags=re.I | re.S)
    content = re.sub(r"<!--.*?-->", " ", content, flags=re.S)
    content = re.sub(r"<[^>]+>", " ", content)
    return html.unescape(content)


def _validate_type(content: bytes, filename: str, mime_type: str) -> str:
    suffix = Path(filename).suffix.casefold()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported file extension: {suffix or '<none>'}")
    if mime_type not in SUPPORTED_MIME_TYPES and mime_type != "application/octet-stream":
        raise ValueError(f"unsupported MIME type: {mime_type}")
    if suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError("PDF extension does not match file signature")
        if mime_type not in {"application/pdf", "application/octet-stream"}:
            raise ValueError("PDF extension does not match MIME type")
    elif mime_type == "application/pdf":
        raise ValueError("PDF MIME type requires .pdf extension")
    return suffix


def _ocr_pdf(content: bytes, languages: str, timeout_seconds: int) -> list[ExtractedPage]:
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
            timeout=timeout_seconds,
        )
        for index, image_path in enumerate(sorted(root.glob("page-*.png")), start=1):
            completed = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", languages, "--psm", "6"],
                check=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
            pages.append(ExtractedPage(page=index, text=_normalize(completed.stdout.decode("utf-8"))))
    return pages


def extract_pages(
    content: bytes,
    filename: str,
    mime_type: str,
    ocr_enabled: bool,
    ocr_languages: str,
    *,
    max_pdf_pages: int = 500,
    ocr_timeout_seconds: int = 300,
) -> tuple[list[ExtractedPage], str]:
    if not content:
        raise ValueError("empty document")
    suffix = _validate_type(content, filename, mime_type)
    if suffix == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(content), strict=True)
        except Exception as exc:
            raise ValueError("malformed PDF") from exc
        if reader.is_encrypted:
            raise ValueError("encrypted PDF is not accepted")
        if len(reader.pages) > max_pdf_pages:
            raise ValueError("PDF page count exceeds configured limit")
        pages = [
            ExtractedPage(page=index, text=_normalize(page.extract_text() or ""))
            for index, page in enumerate(reader.pages, start=1)
        ]
        printable = sum(len(page.text) for page in pages)
        if printable >= max(80, len(pages) * 30):
            return pages, "pdf_text"
        if not ocr_enabled:
            raise ValueError("PDF has insufficient embedded text and OCR is disabled")
        try:
            ocr_pages = _ocr_pdf(content, ocr_languages, ocr_timeout_seconds)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("OCR execution failed") from exc
        if not any(page.text for page in ocr_pages):
            raise ValueError("OCR produced no text")
        return ocr_pages, "pdf_ocr"

    try:
        decoded = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("text document must be valid UTF-8") from exc
    if suffix == ".json":
        try:
            decoded = json.dumps(json.loads(decoded), ensure_ascii=False, indent=2)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON document") from exc
    elif suffix in {".html", ".htm"}:
        decoded = _strip_html(decoded)
    normalized = _normalize(decoded)
    if not normalized:
        raise ValueError("document contains no extractable text")
    return [ExtractedPage(page=None, text=normalized)], "plain_text"


def _hard_chunks(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    stride = max_chars - overlap_chars
    if stride <= 0:
        raise ValueError("overlap_chars must be smaller than max_chars")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start += stride
    return chunks


def make_spans(
    pages: list[ExtractedPage],
    max_chars: int = 1400,
    overlap_chars: int = 180,
    *,
    max_spans: int = 20_000,
) -> list[dict[str, object]]:
    if max_chars < 100:
        raise ValueError("max_chars is too small")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("invalid overlap_chars")
    output: list[dict[str, object]] = []
    ordinal = 0
    for page in pages:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", page.text) if part.strip()]
        buffer = ""
        previous_tail = ""
        for paragraph in paragraphs:
            for piece in _hard_chunks(paragraph, max_chars, overlap_chars):
                proposal = f"{buffer}\n\n{piece}".strip() if buffer else piece
                if len(proposal) <= max_chars:
                    buffer = proposal
                    continue
                if buffer:
                    output.append(
                        {"ordinal": ordinal, "page": page.page, "section": None, "text": buffer}
                    )
                    ordinal += 1
                    previous_tail = buffer[-overlap_chars:] if overlap_chars else ""
                buffer = f"{previous_tail} {piece}".strip()
                if len(buffer) > max_chars:
                    buffer = buffer[-max_chars:]
                if len(output) >= max_spans:
                    raise ValueError("document exceeds maximum span count")
        if buffer:
            output.append({"ordinal": ordinal, "page": page.page, "section": None, "text": buffer})
            ordinal += 1
        if len(output) > max_spans:
            raise ValueError("document exceeds maximum span count")
    if not output:
        raise ValueError("document yielded no evidence spans")
    if any(len(str(span["text"])) > max_chars for span in output):
        raise AssertionError("chunking invariant violated")
    return output
