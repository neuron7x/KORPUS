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
    with pytest.raises(ValueError, match="requires .pdf"):
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
            "".join(random_source.choice(alphabet) for _ in range(random_source.randint(1, 900))).strip() or "x"
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
