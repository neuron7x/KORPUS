from __future__ import annotations

import html
import json
import os
import re
import resource
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

SUPPORTED_SUFFIXES = {".txt", ".md", ".json", ".html", ".htm", ".pdf"}
SUPPORTED_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "application/json",
    "text/html",
    "application/pdf",
}
TEXT_MIME_PREFIXES = ("text/plain", "text/html", "application/json")


@dataclass(frozen=True)
class ExtractedPage:
    page: int | None
    text: str


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "iframe", "object", "svg", "template", "noscript"}:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag.casefold() in {
            "p", "div", "section", "article", "header", "footer", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "iframe", "object", "svg", "template", "noscript"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif self._ignored_depth == 0 and tag.casefold() in {"p", "div", "section", "article", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)

    def text(self) -> str:
        return html.unescape(" ".join(self.parts))


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_html(content: str) -> str:
    parser = _VisibleTextParser()
    try:
        parser.feed(content)
        parser.close()
    except (ValueError, AssertionError) as exc:
        raise ValueError("malformed HTML document") from exc
    return parser.text()


def _detected_mime(path: Path, timeout_seconds: float = 3.0) -> str | None:
    try:
        completed = subprocess.run(
            ["file", "--brief", "--mime-type", "--", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip().casefold()


def _validate_type_path(path: Path, filename: str, mime_type: str) -> str:
    suffix = Path(filename).suffix.casefold()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported file extension: {suffix or '<none>'}")
    if mime_type not in SUPPORTED_MIME_TYPES and mime_type != "application/octet-stream":
        raise ValueError(f"unsupported MIME type: {mime_type}")
    with path.open("rb") as handle:
        prefix = handle.read(16)
    detected = _detected_mime(path)
    if suffix == ".pdf":
        if not prefix.startswith(b"%PDF-"):
            raise ValueError("PDF extension does not match file signature")
        if mime_type not in {"application/pdf", "application/octet-stream"}:
            raise ValueError("PDF extension does not match MIME type")
        if detected is not None and detected != "application/pdf":
            raise ValueError(f"PDF content detected as {detected}")
    elif mime_type == "application/pdf":
        raise ValueError("PDF MIME type requires .pdf extension")
    elif detected is not None:
        if suffix == ".json" and detected not in {"application/json", "text/plain"}:
            raise ValueError(f"JSON content detected as {detected}")
        if suffix in {".html", ".htm"} and detected not in {"text/html", "text/plain"}:
            raise ValueError(f"HTML content detected as {detected}")
        if suffix in {".txt", ".md"} and not detected.startswith("text/"):
            raise ValueError(f"text content detected as {detected}")
    return suffix


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("extraction time budget exceeded")
    return remaining


def _ocr_pdf_path(path: Path, languages: str, deadline: float, max_pages: int) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    with tempfile.TemporaryDirectory(prefix="korpus-ocr-") as directory:
        root = Path(directory)
        prefix = root / "page"
        subprocess.run(
            ["pdftoppm", "-png", "-r", "220", "-f", "1", "-l", str(max_pages), str(path), str(prefix)],
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
            pages.append(ExtractedPage(page=index, text=_normalize(completed.stdout.decode("utf-8"))))
    return pages


def extract_pages_from_path(
    path: Path,
    filename: str,
    mime_type: str,
    ocr_enabled: bool,
    ocr_languages: str,
    *,
    max_pdf_pages: int = 500,
    ocr_total_timeout_seconds: int = 300,
) -> tuple[list[ExtractedPage], str]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("empty document")
    suffix = _validate_type_path(path, filename, mime_type)
    deadline = time.monotonic() + ocr_total_timeout_seconds
    if suffix == ".pdf":
        try:
            reader = PdfReader(str(path), strict=True)
        except (OSError, ValueError, TypeError, PdfReadError) as exc:
            raise ValueError("malformed PDF") from exc
        if reader.is_encrypted:
            raise ValueError("encrypted PDF is not accepted")
        if len(reader.pages) > max_pdf_pages:
            raise ValueError("PDF page count exceeds configured limit")
        pages: list[ExtractedPage] = []
        try:
            for index, page in enumerate(reader.pages, start=1):
                _remaining(deadline)
                pages.append(ExtractedPage(page=index, text=_normalize(page.extract_text() or "")))
        except (KeyError, ValueError, TypeError, RecursionError, PdfReadError) as exc:
            raise ValueError("PDF text extraction failed") from exc
        printable = sum(len(page.text) for page in pages)
        if printable >= max(80, len(pages) * 30):
            return pages, "pdf_text"
        if not ocr_enabled:
            raise ValueError("PDF has insufficient embedded text and OCR is disabled")
        try:
            ocr_pages = _ocr_pdf_path(path, ocr_languages, deadline, max_pdf_pages)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("OCR execution failed") from exc
        if not any(page.text for page in ocr_pages):
            raise ValueError("OCR produced no text")
        return ocr_pages, "pdf_ocr"

    try:
        decoded = path.read_text(encoding="utf-8-sig", errors="strict")
    except (UnicodeDecodeError, OSError) as exc:
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
    suffix = Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(prefix="korpus-extract-", suffix=suffix, delete=False) as handle:
        handle.write(content)
        path = Path(handle.name)
    try:
        return extract_pages_from_path(
            path,
            filename,
            mime_type,
            ocr_enabled,
            ocr_languages,
            max_pdf_pages=max_pdf_pages,
            ocr_total_timeout_seconds=ocr_timeout_seconds,
        )
    finally:
        path.unlink(missing_ok=True)


def _sandbox_limits(memory_limit_mb: int, cpu_seconds: int, output_limit_bytes: int) -> None:
    memory = memory_limit_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit_bytes, output_limit_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))


def extract_pages_sandboxed(
    path: Path,
    filename: str,
    mime_type: str,
    ocr_enabled: bool,
    ocr_languages: str,
    *,
    max_pdf_pages: int,
    ocr_total_timeout_seconds: int,
    timeout_seconds: int,
    memory_limit_mb: int,
    output_limit_bytes: int,
) -> tuple[list[ExtractedPage], str]:
    request = {
        "path": str(path.resolve()),
        "filename": filename,
        "mime_type": mime_type,
        "ocr_enabled": ocr_enabled,
        "ocr_languages": ocr_languages,
        "max_pdf_pages": max_pdf_pages,
        "ocr_total_timeout_seconds": ocr_total_timeout_seconds,
    }
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "PYTHONHASHSEED": "0",
        "LC_ALL": "C.UTF-8",
        "NO_PROXY": "*",
        "no_proxy": "*",
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "korpus.infrastructure.parser_worker"],
            input=json.dumps(request, separators=(",", ":")),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=environment,
            cwd=str(path.parent),
            preexec_fn=lambda: _sandbox_limits(memory_limit_mb, timeout_seconds, output_limit_bytes),
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("parser sandbox timeout") from exc
    except OSError as exc:
        raise ValueError("parser sandbox unavailable") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip()[:500] or "parser sandbox failed"
        raise ValueError(message)
    if len(completed.stdout.encode("utf-8")) > output_limit_bytes:
        raise ValueError("parser sandbox output exceeds limit")
    try:
        payload: dict[str, Any] = json.loads(completed.stdout)
        pages = [ExtractedPage(**item) for item in payload["pages"]]
        method = str(payload["method"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid parser sandbox response") from exc
    return pages, method


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
                    output.append({"ordinal": ordinal, "page": page.page, "section": None, "text": buffer})
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
