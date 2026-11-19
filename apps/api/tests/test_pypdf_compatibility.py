"""Exercise the installed PDF parser through real bytes and the worker boundary.

The existing reader doubles exercise refusal branches, while the encrypted fixture
has a blank page. Neither detects a major-version regression that loses text or its
owner-restriction provenance. These synthetic PDFs carry exact Unicode text and page
order; no document corpus, external renderer, or mocked reader is involved.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from korpus.domain.models import ExtractedPage
from korpus.infrastructure import extraction, pdf_extraction
from korpus.infrastructure.extraction import extract_pages_from_path, extract_pages_sandboxed
from pypdf import PdfReader, PdfWriter, apply_configuration
from pypdf.errors import LimitReachedError, PdfReadError

TEXTS = (
    "Synthetic first page. This public example contains ordinary document text for parser "
    "compatibility checks. Український текст зберігається без втрат.",
    "Synthetic second page. Its distinct text proves that extraction preserves page order "
    "and page boundaries. Друга сторінка містить інший перевірний текст.",
)


def _text_pdf(*, duplicate_root: bool = False) -> bytes:
    """Build tiny PDFs independently of the parser's writer and font heuristics.

    The explicit ToUnicode map makes the expected extracted text part of the fixture,
    including Cyrillic, without depending on installed fonts or a PDF generator.
    """
    codes = {character: index for index, character in enumerate(sorted(set("".join(TEXTS))), 1)}

    def stream(data: bytes) -> bytes:
        return f"<< /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"

    mappings = "\n".join(
        f"<{code:02x}> <{character.encode('utf-16-be').hex()}>" for character, code in codes.items()
    )
    cmap = (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /SyntheticUnicode def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<00> <ff>\nendcodespacerange\n"
        f"{len(codes)} beginbfchar\n{mappings}\nendbfchar\n"
        "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend"
    ).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [5 0 R 7 0 R] /Count 2 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 4 0 R >>",
        stream(cmap),
    ]
    for index, text in enumerate(TEXTS):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1200 300] "
            b"/Resources << /Font << /F1 3 0 R >> >> "
            + f"/Contents {6 + index * 2} 0 R >>".encode()
        )
        encoded = bytes(codes[character] for character in text).hex()
        objects.append(stream(f"BT /F1 10 Tf 20 200 Td <{encoded}> Tj ET".encode()))
    document = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(document)
    document.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    extra_root = " /Root 1 0 R" if duplicate_root else ""
    document.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R{extra_root} >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(document)


def _encrypt(document: bytes, password: str, algorithm: str) -> bytes:
    writer = PdfWriter(clone_from=io.BytesIO(document))
    writer.encrypt(user_password=password, owner_password="synthetic-owner", algorithm=algorithm)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _hybrid_pdf(*, duplicate_root: bool = False) -> bytes:
    """Add a tiny valid hybrid cross-reference update to the text fixture."""
    document = bytearray(_text_pdf())
    previous_xref = int(document.rsplit(b"startxref\n", 1)[1].splitlines()[0])
    stream_offset = len(document)
    entries = b"\x00" + bytes(4) + b"\xff\xff"
    entries += b"\x01" + stream_offset.to_bytes(4, "big") + bytes(2)
    document.extend(
        f"9 0 obj\n<< /Type /XRef /Size 10 /Index [0 1 9 1] /W [1 4 2] "
        f"/Length {len(entries)} >>\nstream\n".encode()
        + entries
        + b"\nendstream\nendobj\n"
    )
    xref = len(document)
    extra_root = " /Root 1 0 R" if duplicate_root else ""
    document.extend(
        f"xref\n9 1\n{stream_offset:010d} 00000 n \ntrailer\n"
        f"<< /Size 10 /Root 1 0 R{extra_root} /Prev {previous_xref} "
        f"/XRefStm {stream_offset} >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(document)


def _extract(
    path: Path, sandboxed: bool, *, max_pages: int = 2, ocr_enabled: bool = False
) -> tuple[list[ExtractedPage], str]:
    arguments = (path, path.name, "application/pdf", ocr_enabled, "eng+ukr")
    if sandboxed:
        return extract_pages_sandboxed(
            *arguments,
            max_pdf_pages=max_pages,
            ocr_total_timeout_seconds=10,
            timeout_seconds=10,
            memory_limit_mb=512,
            output_limit_bytes=32_768,
        )
    return extract_pages_from_path(
        *arguments, max_pdf_pages=max_pages, ocr_total_timeout_seconds=10
    )


@pytest.mark.parametrize("sandboxed", [False, True], ids=["direct", "worker"])
@pytest.mark.parametrize("algorithm", [None, "RC4-128", "AES-256"])
def test_real_pdf_preserves_unicode_page_order_and_owner_provenance(
    tmp_path: Path, sandboxed: bool, algorithm: str | None
) -> None:
    content = _text_pdf()
    if algorithm is not None:
        content = _encrypt(content, "", algorithm)
    path = tmp_path / "public.pdf"
    path.write_bytes(content)

    pages, method = _extract(path, sandboxed)

    assert [(page.page, page.text) for page in pages] == list(enumerate(TEXTS, 1))
    assert method == ("pdf_text_owner_restricted" if algorithm else "pdf_text")


@pytest.mark.parametrize("sandboxed", [False, True], ids=["direct", "worker"])
@pytest.mark.parametrize("algorithm", ["RC4-128", "AES-256"])
def test_real_pdf_with_a_user_password_is_refused(
    tmp_path: Path, sandboxed: bool, algorithm: str
) -> None:
    path = tmp_path / "password.pdf"
    path.write_bytes(_encrypt(_text_pdf(), "synthetic-reader-password", algorithm))

    with pytest.raises(ValueError, match="password that was not supplied"):
        _extract(path, sandboxed)


@pytest.mark.parametrize("sandboxed", [False, True], ids=["direct", "worker"])
@pytest.mark.parametrize("duplicate_root", [False, True], ids=["strict", "lenient"])
def test_real_pdf_page_limit_holds_in_both_reader_modes(
    tmp_path: Path, sandboxed: bool, duplicate_root: bool
) -> None:
    path = tmp_path / "two-pages.pdf"
    path.write_bytes(_text_pdf(duplicate_root=duplicate_root))

    with pytest.raises(ValueError, match="page count exceeds configured limit"):
        _extract(path, sandboxed, max_pages=1)


def test_real_lenient_pdf_records_the_fallback_and_preserves_text(tmp_path: Path) -> None:
    content = _text_pdf(duplicate_root=True)
    # Prove this fixture reaches the lenient branch instead of silently testing strict parsing.
    with pytest.raises(PdfReadError, match="Multiple definitions"):
        PdfReader(io.BytesIO(content), strict=True)
    path = tmp_path / "duplicate-root.pdf"
    path.write_bytes(content)

    pages, method = _extract(path, False)

    assert [(page.page, page.text) for page in pages] == list(enumerate(TEXTS, 1))
    assert method == "pdf_text_lenient"


@pytest.mark.parametrize("sandboxed", [False, True], ids=["direct", "worker"])
def test_truncated_pdf_is_contained_as_a_document_refusal(tmp_path: Path, sandboxed: bool) -> None:
    path = tmp_path / "truncated.pdf"
    path.write_bytes(_text_pdf()[:120])

    with pytest.raises(ValueError, match="malformed PDF") as raised:
        _extract(path, sandboxed)

    assert not isinstance(raised.value, PdfReadError)


def _unexpected_ocr(*arguments: object, **keywords: object) -> list[ExtractedPage]:
    pytest.fail("a parser resource limit must not trigger OCR")


@pytest.mark.parametrize("duplicate_root", [False, True], ids=["strict", "lenient"])
def test_real_xref_resource_limit_is_contained_without_an_extra_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, duplicate_root: bool
) -> None:
    path = tmp_path / "hybrid.pdf"
    path.write_bytes(_hybrid_pdf(duplicate_root=duplicate_root))
    # The same document is readable with ordinary limits: this is a resource
    # refusal, not a malformed fixture that fails before reaching the bound.
    pages, method = _extract(path, False)
    assert [page.text for page in pages] == list(TEXTS)
    assert method == ("pdf_text_lenient" if duplicate_root else "pdf_text")
    attempts: list[bool] = []

    def bounded_reader(stream: str, *, strict: bool) -> PdfReader:
        attempts.append(strict)
        return PdfReader(stream, strict=strict, xref_stream_maximum_entries=1)

    monkeypatch.setattr(extraction, "PdfReader", bounded_reader)
    monkeypatch.setattr(pdf_extraction, "_ocr_pages", _unexpected_ocr)
    with pytest.raises(ValueError, match="PDF parser resource limit exceeded") as raised:
        _extract(path, False, ocr_enabled=True)

    assert isinstance(raised.value.__cause__, LimitReachedError)
    assert attempts == ([True, False] if duplicate_root else [True])


def test_real_lazy_stream_resource_limit_is_contained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bounded-stream.pdf"
    path.write_bytes(_text_pdf())
    monkeypatch.setattr(pdf_extraction, "_ocr_pages", _unexpected_ocr)
    with apply_configuration(maximum_declared_stream_length=1):
        # Construction and page-tree traversal succeed; reading text consumes the
        # first actual stream and must surface a document-level refusal instead.
        reader = PdfReader(str(path), strict=True)
        assert len(reader.pages) == 2
        with pytest.raises(ValueError, match="PDF parser resource limit exceeded") as raised:
            _extract(path, False, ocr_enabled=True)

    assert isinstance(raised.value.__cause__, LimitReachedError)
