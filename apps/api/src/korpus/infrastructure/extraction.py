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
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from korpus.domain.models import ExtractedPage

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUPPORTED_SUFFIXES = {".txt", ".md", ".json", ".html", ".htm", ".pdf", ".docx"}
SUPPORTED_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "application/json",
    "text/html",
    "application/pdf",
    DOCX_MIME_TYPE,
}
TEXT_MIME_PREFIXES = ("text/plain", "text/html", "application/json")


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
            "p", "div", "section", "article", "header", "footer", "br", "li", "tr",
            "h1", "h2", "h3", "h4", "h5", "h6",
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "iframe", "object", "svg", "template", "noscript"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif self._ignored_depth == 0 and tag.casefold() in {
            "p", "div", "section", "article", "li", "tr",
        }:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)

    def text(self) -> str:
        return html.unescape(" ".join(self.parts))


def _normalize(text: str) -> str:
    """Whitespace made uniform, with the column gap deliberately preserved.

    `re.sub(r"[ \t]+", " ", text)` used to run here and collapsed every run of spaces
    and every tab to one space. That is the gap `table_integrity.COLUMN_GAP` looks for,
    so on 2026-08-06 a probe found that `assess_table_integrity` could not fire on any
    real document: by the time it saw the text, every column boundary had been erased.
    The module exists against a specific failure — a table row that lost a cell shifts
    its figures left, so a number is quoted under another column's heading, and the
    passage stays grammatical while stating a norm that does not exist — and it was
    running on text where that damage was invisible.

    Runs of *three* or more spaces are kept, and tabs are kept. Two spaces after a full
    stop is typography; three is a column, and a tab always is.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)
    # Collapse only runs that cannot be a column boundary, and leave tabs alone.
    text = re.sub(r"(?<! ) {2}(?! )", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
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
    elif suffix == ".docx":
        # PK\x03\x04. Extension, declared MIME and the first four bytes have to agree
        # before a ZIP parser sees the file: the whole point of the check is that a
        # renamed archive does not get to choose its own reader.
        if not prefix.startswith(b"PK\x03\x04"):
            raise ValueError("DOCX extension does not match file signature")
        if mime_type not in {DOCX_MIME_TYPE, "application/octet-stream"}:
            raise ValueError("DOCX extension does not match MIME type")
        if detected is not None and detected not in {DOCX_MIME_TYPE, "application/zip"}:
            raise ValueError(f"DOCX content detected as {detected}")
    elif mime_type == "application/pdf":
        raise ValueError("PDF MIME type requires .pdf extension")
    elif mime_type == DOCX_MIME_TYPE:
        raise ValueError("DOCX MIME type requires .docx extension")
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


def _ocr_pdf_path(
    path: Path, languages: str, deadline: float, max_pages: int
) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    with tempfile.TemporaryDirectory(prefix="korpus-ocr-") as directory:
        root = Path(directory)
        prefix = root / "page"
        subprocess.run(
            [
                "pdftoppm", "-png", "-r", "220", "-f", "1",
                "-l", str(max_pages), str(path), str(prefix),
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
                ExtractedPage(page=index, text=_normalize(completed.stdout.decode("utf-8")))
            )
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

    if suffix == ".docx":
        paragraphs = _docx_paragraphs(_docx_body_xml(path))
        if not paragraphs:
            raise ValueError("DOCX contains no extractable text")
        # One page, like every other flow format: DOCX has no page boundaries until it
        # is laid out, and inventing them would put a page number on a citation that no
        # printed copy agrees with.
        return [ExtractedPage(page=None, text=_normalize("\n\n".join(paragraphs)))], "docx_text"

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
    with tempfile.NamedTemporaryFile(
        prefix="korpus-extract-", suffix=suffix, delete=False
    ) as handle:
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
        # Absolute, because `cwd` below is the *document's* directory, not this process's.
        # A relative `PYTHONPATH=apps/api/src` — which is what the Makefile and every
        # shell invocation naturally carry — resolves against that directory and finds
        # nothing, so the worker died with "Error while finding module" on every single
        # file. Nothing about the failure named the cwd, so it read as a broken document.
        "PYTHONPATH": os.pathsep.join(
            str(Path(entry).resolve())
            for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep)
            if entry
        ),
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
            # Explicitly no CalledProcessError: the returncode is inspected below and the
            # worker's stderr is turned into the ValueError message the caller expects.
            check=False,
            env=environment,
            cwd=str(path.parent),
            preexec_fn=lambda: _sandbox_limits(
                memory_limit_mb, timeout_seconds, output_limit_bytes
            ),
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



#: OOXML is a ZIP. Every one of these bounds exists because the file is untrusted: a
#: 40 KB archive can declare a 4 GB member, and a parser that believes the header
#: allocates it. Chosen to be far above any real order and far below anything that
#: matters to a container with a memory limit.
_DOCX_MAX_MEMBERS = 512
_DOCX_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_DOCX_MAX_TOTAL_BYTES = 128 * 1024 * 1024
_DOCX_BODY = "word/document.xml"
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_body_xml(path: Path) -> bytes:
    """The document body, with the archive checked before anything is decompressed.

    Deliberately stdlib-only. `python-docx` pulls in lxml, a C extension, and putting a
    new binary parser in front of untrusted uploads to read a ZIP of XML is a poor
    trade: the format needs about forty lines and zipfile already reports declared sizes
    without expanding them.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > _DOCX_MAX_MEMBERS:
                raise ValueError("DOCX archive declares too many members")
            total = 0
            for member in members:
                if member.file_size > _DOCX_MAX_MEMBER_BYTES:
                    raise ValueError("DOCX member exceeds the size limit")
                total += member.file_size
            if total > _DOCX_MAX_TOTAL_BYTES:
                raise ValueError("DOCX archive exceeds the uncompressed size limit")
            if _DOCX_BODY not in archive.namelist():
                raise ValueError("DOCX archive has no word/document.xml")
            body = archive.read(_DOCX_BODY)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("malformed DOCX") from exc
    # No DTD, no entity declarations. `xml.etree` does not resolve external entities,
    # but it does expand internal ones, which is the billion-laughs shape. Refusing the
    # declaration outright is simpler than bounding the expansion and cannot be
    # miscounted.
    head = body[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ValueError("DOCX body declares a DTD or entity")
    return body


def _docx_paragraphs(body: bytes) -> list[str]:
    """Visible paragraph text, in document order.

    Only the body. Headers and footers are page furniture — a page number and a
    classification stamp repeated on every sheet — and pulling them in would put text
    into quotable spans that the document does not say once.
    """
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ValueError("DOCX body is not well-formed XML") from exc
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{_WORD_NS}p"):
        pieces: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{_WORD_NS}t" and node.text:
                pieces.append(node.text)
            elif node.tag == f"{_WORD_NS}tab":
                # A tab is a column boundary in a flattened table, and
                # `table_integrity.py` looks for exactly that gap to notice a row that
                # lost a cell. Dropping it would erase the evidence of the damage.
                pieces.append("\t")
            elif node.tag in {f"{_WORD_NS}br", f"{_WORD_NS}cr"}:
                pieces.append("\n")
        text = "".join(pieces).strip()
        if text:
            paragraphs.append(text)
    return paragraphs

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


#: Structural headings of Ukrainian normative acts, anchored to the start of a line and
#: bounded in length. A citation that says only "page 4" is not an address a reader can
#: check against a printed order; "Стаття 12" is. Bare numbered clauses ("1. …") are
#: deliberately excluded: in these documents they are the clause itself far more often
#: than a heading, and a wrong section is worse than none.
_SECTION_HEADING = re.compile(
    r"^[ \t]*("
    r"(?:РОЗДІЛ|Розділ|ГЛАВА|Глава|СТАТТЯ|Стаття|ПУНКТ|Пункт|ДОДАТОК|Додаток|ЧАСТИНА|Частина)"
    r"[ \t]+[^\n]{0,80}"
    r"|§[ \t]*\d+[^\n]{0,60}"
    r")[ \t]*$",
    re.MULTILINE,
)


def section_markers(text: str) -> list[tuple[int, str]]:
    """Offsets of structural headings within a page, in document order."""

    return [
        (match.start(1), " ".join(match.group(1).split()))
        for match in _SECTION_HEADING.finditer(text)
    ]


def _section_at(markers: list[tuple[int, str]], offset: int) -> str | None:
    """The last heading at or before `offset`; None before the first heading."""

    label: str | None = None
    for start, value in markers:
        if start > offset:
            break
        label = value
    return label


def _cut_point(window: str, minimum: int) -> int:
    """Where to end a window so it stops on a boundary the document itself has."""
    for separator in ("\n\n", "\n", ". ", " "):
        cut = window.rfind(separator)
        if cut >= minimum:
            return cut + len(separator)
    return len(window)


def make_spans(
    pages: list[ExtractedPage],
    max_chars: int = 1400,
    overlap_chars: int = 180,
    *,
    max_spans: int = 20_000,
) -> list[dict[str, object]]:
    """Every span is a slice of its page, never assembled from two of them.

    The previous implementation joined the tail of one span to the head of the next
    with a space (`f"{previous_tail} {piece}"`) and paragraphs with a blank line. Both
    manufacture text: a sentence that exists in no document comes out of the answer as
    a verbatim quote, stamped with `quote_hash` and `source_hash`. Reproduced end to
    end on 2026-08-03 — `status=answered`, `quote in source == False`,
    `support_score=1.0`. Since a citation is the one thing KORPUS promises to get
    right, spans are now slices `page.text[start:end]`, so being a substring of the
    document is a property of the construction and not of a later check. The assertion
    at the end is there for the day someone changes the construction.
    """
    if max_chars < 100:
        raise ValueError("max_chars is too small")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("invalid overlap_chars")
    output: list[dict[str, object]] = []
    ordinal = 0
    for page in pages:
        text = page.text
        markers = section_markers(text)
        position = 0
        while position < len(text):
            end = min(len(text), position + max_chars)
            if end < len(text):
                end = position + _cut_point(text[position:end], max_chars // 4)
            raw = text[position:end]
            chunk = raw.strip()
            if chunk:
                offset = position + (len(raw) - len(raw.lstrip()))
                if len(output) >= max_spans:
                    raise ValueError("document exceeds maximum span count")
                # The section is the heading in force where the span starts, so a
                # citation can be checked against a printed order rather than only
                # against this database.
                output.append(
                    {
                        "ordinal": ordinal,
                        "page": page.page,
                        "section": _section_at(markers, offset),
                        "text": chunk,
                    }
                )
                ordinal += 1
            if end >= len(text):
                break
            # Step forward by at least one character so a pathological page cannot
            # spin here, and keep the overlap so no local window is lost at a seam.
            position = max(position + 1, end - overlap_chars)
    if not output:
        raise ValueError("document yielded no evidence spans")
    if any(len(str(span["text"])) > max_chars for span in output):
        raise AssertionError("chunking invariant violated")
    by_page = {page.page: page.text for page in pages}
    if any(str(span["text"]) not in by_page[span["page"]] for span in output):  # type: ignore[index]
        raise AssertionError("span is not a substring of its page")
    return output


class DocumentExtractor:
    """The `Extractor` port, bound to this module's functions.

    A class rather than the module itself so the composition root passes an object and
    `application/ingestion.py` needs no import from `korpus.infrastructure`. The sandbox
    decision stays with the caller: this only carries it out.
    """

    def extract_pages(
        self,
        *,
        path: Path,
        filename: str,
        mime_type: str,
        sandboxed: bool,
        ocr_enabled: bool,
        ocr_languages: str,
        max_pdf_pages: int,
        ocr_total_timeout_seconds: int,
        timeout_seconds: int,
        memory_limit_mb: int,
        output_limit_bytes: int,
    ) -> tuple[list[ExtractedPage], str]:
        if sandboxed:
            return extract_pages_sandboxed(
                path=path,
                filename=filename,
                mime_type=mime_type,
                ocr_enabled=ocr_enabled,
                ocr_languages=ocr_languages,
                max_pdf_pages=max_pdf_pages,
                ocr_total_timeout_seconds=ocr_total_timeout_seconds,
                timeout_seconds=timeout_seconds,
                memory_limit_mb=memory_limit_mb,
                output_limit_bytes=output_limit_bytes,
            )
        return extract_pages_from_path(
            path=path,
            filename=filename,
            mime_type=mime_type,
            ocr_enabled=ocr_enabled,
            ocr_languages=ocr_languages,
            max_pdf_pages=max_pdf_pages,
            ocr_total_timeout_seconds=ocr_total_timeout_seconds,
        )

    def make_spans(
        self,
        pages: list[ExtractedPage],
        *,
        max_chars: int,
        overlap_chars: int,
        max_spans: int,
    ) -> list[dict[str, object]]:
        return make_spans(
            pages, max_chars=max_chars, overlap_chars=overlap_chars, max_spans=max_spans
        )
