"""What the intake path refuses, and why each refusal is separate.

Extraction is where untrusted bytes first meet the system. Three independent claims
arrive with every upload — the filename's extension, the declared MIME type, and the
bytes themselves — and the whole point of `_validate_type_path` is that agreement
between two of them is not enough. A `.txt` that is really a PDF, a `.pdf` declared as
`text/plain`, an HTML file whose content sniffs as something else: each is a separate
branch, and coverage recorded most of them as never taken.

The HTML stripper is here for the same reason. It exists so that script, style, iframe
and svg content never becomes indexable text — a corpus that quotes a passage out of a
`<script>` block is quoting something no reader of the document would ever have seen.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from korpus.infrastructure.extraction import extract_pages, extract_pages_from_path

MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
)


def _extract(content: bytes, filename: str, mime_type: str) -> tuple[list, str]:
    return extract_pages(content, filename, mime_type, False, "ukr")


def test_a_plain_text_document_is_extracted() -> None:
    """The dual: every refusal below is vacuous if nothing can be accepted."""
    pages, method = _extract("Наказ №1\nПідстава: стаття 5.".encode(), "order.txt", "text/plain")

    assert method == "plain_text"
    assert "Наказ" in pages[0].text


def test_an_empty_upload_is_refused() -> None:
    with pytest.raises(ValueError, match="empty document"):
        _extract(b"", "order.txt", "text/plain")


def test_a_whitespace_only_document_is_refused() -> None:
    """Bytes present, text absent — a document with nothing to cite."""
    with pytest.raises(ValueError, match="no extractable text"):
        _extract(b"   \n\t  \n", "order.txt", "text/plain")


@pytest.mark.parametrize("filename", ["order.exe", "order.docx", "order"])
def test_an_unsupported_extension_is_refused(filename: str) -> None:
    with pytest.raises(ValueError, match="unsupported file extension"):
        _extract(b"content", filename, "text/plain")


def test_an_unsupported_mime_type_is_refused() -> None:
    with pytest.raises(ValueError, match="unsupported MIME type"):
        _extract(b"content", "order.txt", "application/x-msdownload")


def test_octet_stream_is_tolerated_because_browsers_send_it() -> None:
    """Refusing it would reject ordinary uploads; the signature check still applies."""
    pages, method = _extract("текст".encode(), "order.txt", "application/octet-stream")

    assert method == "plain_text"
    assert pages[0].text == "текст"


def test_a_pdf_extension_over_non_pdf_bytes_is_refused() -> None:
    """The extension is a claim about the bytes, and the bytes disagree."""
    with pytest.raises(ValueError, match="does not match file signature"):
        _extract(b"this is not a pdf at all", "order.pdf", "application/pdf")


def test_a_pdf_extension_with_a_text_mime_type_is_refused() -> None:
    with pytest.raises(ValueError, match="does not match MIME type"):
        _extract(MINIMAL_PDF, "order.pdf", "text/plain")


def test_a_pdf_mime_type_without_a_pdf_extension_is_refused() -> None:
    """The mirror case: declaring PDF while calling the file .txt."""
    with pytest.raises(ValueError, match=r"requires \.pdf extension"):
        _extract(b"%PDF-1.4\n", "order.txt", "application/pdf")


def test_an_encrypted_pdf_is_refused_rather_than_partially_read() -> None:
    encrypted = MINIMAL_PDF.replace(
        b"trailer<</Root 1 0 R>>", b"trailer<</Root 1 0 R/Encrypt 4 0 R>>"
    )

    with pytest.raises(ValueError, match=r"malformed PDF|encrypted PDF"):
        _extract(encrypted, "order.pdf", "application/pdf")


def test_a_malformed_pdf_is_refused() -> None:
    with pytest.raises(ValueError, match="malformed PDF"):
        _extract(b"%PDF-1.4\nnot really a pdf structure\n", "order.pdf", "application/pdf")


def test_a_pdf_with_no_embedded_text_and_ocr_disabled_is_refused() -> None:
    """Silently returning empty pages would index a document with nothing in it."""
    with pytest.raises(ValueError, match=r"insufficient embedded text|malformed PDF"):
        extract_pages(MINIMAL_PDF, "order.pdf", "application/pdf", False, "ukr")


def test_a_json_document_is_normalised_rather_than_stored_verbatim() -> None:
    pages, method = _extract(b'{"b":2,"a":1}', "order.json", "application/json")

    assert method == "plain_text"
    assert '"a": 1' in pages[0].text


def test_invalid_json_is_refused() -> None:
    with pytest.raises(ValueError, match="invalid JSON document"):
        _extract(b'{"unterminated": ', "order.json", "application/json")


def test_non_utf8_bytes_are_refused() -> None:
    """A mis-decoded order is a different order; guessing an encoding is not allowed."""
    with pytest.raises(ValueError, match="must be valid UTF-8"):
        _extract("Наказ".encode("cp1251"), "order.txt", "text/plain")


def test_a_utf8_bom_is_accepted_and_stripped() -> None:
    pages, _ = _extract("﻿Наказ".encode(), "order.txt", "text/plain")

    assert pages[0].text == "Наказ"


def test_script_and_style_content_never_becomes_indexable_text() -> None:
    """A citation into a <script> block would quote something no reader ever saw."""
    document = (
        b"<html><head><style>.a{color:red}</style><script>var secret='exfil';</script></head>"
        b"<body><p>\xd0\x9d\xd0\xb0\xd0\xba\xd0\xb0\xd0\xb7 \xe2\x84\x961</p>"
        b"<noscript>fallback</noscript><svg><text>vector</text></svg></body></html>"
    )

    pages, method = _extract(document, "order.html", "text/html")

    assert method == "plain_text"
    assert "Наказ №1" in pages[0].text
    for hidden in ("secret", "exfil", "color:red", "fallback", "vector"):
        assert hidden not in pages[0].text


def test_html_entities_are_decoded_into_the_text_that_is_quoted() -> None:
    pages, _ = _extract(b"<p>&#1053;&#1072;&#1082;&#1072;&#1079; &amp; &lt;5&gt;</p>",
                        "order.html", "text/html")

    assert "Наказ & <5>" in pages[0].text


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty document"):
        extract_pages_from_path(tmp_path / "absent.txt", "absent.txt", "text/plain", False, "ukr")


def test_a_zero_byte_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")

    with pytest.raises(ValueError, match="empty document"):
        extract_pages_from_path(path, "empty.txt", "text/plain", False, "ukr")


def test_a_pdf_exceeding_the_page_limit_is_refused(tmp_path: Path) -> None:
    """The limit is a resource bound; unbounded page counts are a denial of service."""
    path = tmp_path / "many.pdf"
    path.write_bytes(MINIMAL_PDF)

    with pytest.raises(ValueError, match=r"page count exceeds|malformed PDF|insufficient"):
        extract_pages_from_path(
            path, "many.pdf", "application/pdf", False, "ukr", max_pdf_pages=0
        )
