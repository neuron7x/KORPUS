from korpus.infrastructure.extraction import extract_pages, make_spans


def test_plain_text_extraction_and_chunking():
    pages, method = extract_pages(
        b"Alpha paragraph.\n\nBeta paragraph.",
        "a.txt",
        "text/plain",
        ocr_enabled=False,
        ocr_languages="eng",
    )
    assert method == "plain_text"
    spans = make_spans(pages, max_chars=20, overlap_chars=4)
    assert spans
    assert all(span["text"] for span in spans)


def test_empty_document_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        extract_pages(b"", "a.txt", "text/plain", False, "eng")
