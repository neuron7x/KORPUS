from __future__ import annotations

import random
import string

import pytest
from korpus.infrastructure.extraction import ExtractedPage, extract_pages, make_spans


def test_plain_text_extraction_and_chunking():
    pages, method = extract_pages(
        b"Alpha paragraph.\n\nBeta paragraph.",
        "a.txt",
        "text/plain",
        ocr_enabled=False,
        ocr_languages="eng",
    )
    assert method == "plain_text"
    spans = make_spans(pages, max_chars=100, overlap_chars=10)
    assert spans
    assert all(span["text"] for span in spans)
    assert all(len(str(span["text"])) <= 100 for span in spans)


def test_empty_malformed_and_type_confused_documents_fail_closed():
    with pytest.raises(ValueError, match="empty"):
        extract_pages(b"", "a.txt", "text/plain", False, "eng")
    with pytest.raises(ValueError, match="signature"):
        extract_pages(b"not a pdf", "a.pdf", "application/pdf", False, "eng")
    with pytest.raises(ValueError, match=r"requires .pdf"):
        extract_pages(b"plain", "a.txt", "application/pdf", False, "eng")
    with pytest.raises(ValueError, match="valid UTF-8"):
        extract_pages(b"\xff\xfe", "a.txt", "text/plain", False, "eng")
    with pytest.raises(ValueError, match="invalid JSON"):
        extract_pages(b"{bad", "a.json", "application/json", False, "eng")


def test_html_active_content_is_removed():
    pages, method = extract_pages(
        b'<html><script>exfiltrate()</script><iframe>bad</iframe><p>Allowed text</p></html>',
        "x.html",
        "text/html",
        False,
        "eng",
    )
    assert method == "plain_text"
    assert "Allowed text" in pages[0].text
    assert "exfiltrate" not in pages[0].text
    assert "bad" not in pages[0].text


def test_chunking_invariants_hold_over_seeded_random_corpus():
    random_source = random.Random(20260731)
    alphabet = string.ascii_letters + " абвгдеєжзиіїйклмнопрстуфхцчшщьюя"
    for _ in range(200):
        paragraphs = [
            "".join(
                random_source.choice(alphabet)
                for _ in range(random_source.randint(1, 900))
            ).strip()
            or "x"
            for _ in range(random_source.randint(1, 8))
        ]
        page = ExtractedPage(page=1, text="\n\n".join(paragraphs))
        chunks = make_spans([page], max_chars=240, overlap_chars=40, max_spans=1000)
        assert [chunk["ordinal"] for chunk in chunks] == list(range(len(chunks)))
        assert all(0 < len(str(chunk["text"])) <= 240 for chunk in chunks)
        chunk_texts = [str(chunk["text"]) for chunk in chunks]
        # No local 20-character evidence window may disappear. Long tokens may
        # cross a chunk boundary, but overlap must preserve every local window.
        for paragraph in paragraphs:
            for start in range(0, max(1, len(paragraph) - 19), 11):
                window = paragraph[start : start + 20]
                if len(window) >= 8:
                    assert any(window in chunk for chunk in chunk_texts)


def test_chunking_rejects_invalid_geometry_and_span_explosion():
    page = ExtractedPage(page=1, text="A" * 1000)
    with pytest.raises(ValueError, match="overlap"):
        make_spans([page], max_chars=100, overlap_chars=100)
    with pytest.raises(ValueError, match="maximum span"):
        make_spans([page], max_chars=100, overlap_chars=0, max_spans=2)


def _docx(tmp_path, paragraphs, *, extra=None, doctype=False):
    import zipfile

    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        + ("<!DOCTYPE w:document [<!ENTITY lol 'lol'>]>\n" if doctype else "")
        + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
        + (extra or "")
        + "</w:body></w:document>"
    )
    path = tmp_path / "order.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", body)
    return path


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_a_docx_yields_its_paragraphs_in_order(tmp_path) -> None:
    """DOCX carries the corpus this system is meant for and was not readable at all.

    Implemented with zipfile and xml.etree rather than python-docx: that pulls in lxml,
    a C extension, and putting a new binary parser in front of untrusted uploads to read
    a ZIP of XML is a poor trade for forty lines.
    """
    from korpus.infrastructure.extraction import extract_pages_from_path

    path = _docx(tmp_path, ["Стаття 12. Дистанція.", "Пункт 3. Норматив."])

    pages, method = extract_pages_from_path(
        path=path, filename="order.docx", mime_type=DOCX_MIME,
        ocr_enabled=False, ocr_languages="ukr",
    )

    assert method == "docx_text"
    assert pages[0].page is None  # a flow format has no page until it is laid out
    assert pages[0].text == "Стаття 12. Дистанція.\n\nПункт 3. Норматив."


def test_a_docx_declaring_an_entity_is_refused(tmp_path) -> None:
    """Billion laughs. `xml.etree` expands internal entities, so the declaration is
    refused outright rather than the expansion bounded — a limit can be miscounted, a
    refusal cannot."""
    import pytest
    from korpus.infrastructure.extraction import extract_pages_from_path

    path = _docx(tmp_path, ["текст"], doctype=True)

    with pytest.raises(ValueError, match="DTD or entity"):
        extract_pages_from_path(
            path=path, filename="order.docx", mime_type=DOCX_MIME,
            ocr_enabled=False, ocr_languages="ukr",
        )


def test_a_zip_renamed_to_docx_is_refused_before_the_parser(tmp_path) -> None:
    """A DOCX is a ZIP, so the signature check has to be the extension's, not the
    format's: otherwise a renamed archive chooses its own reader."""
    import pytest
    from korpus.infrastructure.extraction import extract_pages_from_path

    path = tmp_path / "order.docx"
    path.write_bytes(b"not a zip at all")

    with pytest.raises(ValueError, match="signature"):
        extract_pages_from_path(
            path=path, filename="order.docx", mime_type=DOCX_MIME,
            ocr_enabled=False, ocr_languages="ukr",
        )


def test_a_docx_without_a_body_is_refused(tmp_path) -> None:
    import zipfile

    import pytest
    from korpus.infrastructure.extraction import extract_pages_from_path

    path = tmp_path / "order.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")

    with pytest.raises(ValueError, match=r"no word/document\.xml"):
        extract_pages_from_path(
            path=path, filename="order.docx", mime_type=DOCX_MIME,
            ocr_enabled=False, ocr_languages="ukr",
        )


def test_normalisation_keeps_the_column_gap_a_flattened_table_leaves() -> None:
    """The whole reason `table_integrity` exists, and it could never fire.

    `_normalize` collapsed every run of spaces and every tab to one space *before*
    `assess_extraction_quality` saw the text, so the gap `COLUMN_GAP` looks for had
    already been erased. Measured 2026-08-06: `table_structure_lost` on the raw text,
    nothing after normalisation. A row that loses a cell shifts its figures left and a
    number is quoted under another column's heading — the passage stays grammatical and
    states a norm that does not exist.
    """
    from korpus.application.extraction_quality import assess_extraction_quality
    from korpus.infrastructure.extraction import _normalize

    ragged = _normalize("Пункт\tЗначення\tОдиниця\n1\t300\tм\n2\t15\n3\t90\tкм/год\n")
    prose = _normalize(
        "Дистанція між укриттями має бути не менше 300 метрів.  "
        "Норматив розгортання становить 15 хвилин."
    )

    assert "table_structure_lost" in assess_extraction_quality(ragged).flags
    # The dual: two spaces after a full stop is typography, not a column, and a flag a
    # reviewer sees on every document is a flag nobody reads.
    assert assess_extraction_quality(prose).flags == frozenset()
