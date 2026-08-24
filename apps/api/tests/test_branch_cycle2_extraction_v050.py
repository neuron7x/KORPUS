from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from korpus.domain.models import ExtractedPage
from korpus.infrastructure import extraction as ex


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_type_detection_refusal_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _write(tmp_path, "x.pdf", b"%PDF-1.7\nbody")
    monkeypatch.setattr(ex, "_detected_mime", lambda p: "application/x-evil")
    with pytest.raises(ValueError, match="PDF content detected"):
        ex._validate_type_path(pdf, "x.pdf", "application/pdf")

    docx = _write(tmp_path, "x.docx", b"PK\x03\x04rest")
    monkeypatch.setattr(ex, "_detected_mime", lambda p: ex.DOCX_MIME_TYPE)
    with pytest.raises(ValueError, match="DOCX extension does not match MIME"):
        ex._validate_type_path(docx, "x.docx", "text/plain")
    monkeypatch.setattr(ex, "_detected_mime", lambda p: "application/x-evil")
    with pytest.raises(ValueError, match="DOCX content detected"):
        ex._validate_type_path(docx, "x.docx", "application/octet-stream")

    txt = _write(tmp_path, "x.txt", b"hello")
    monkeypatch.setattr(ex, "_detected_mime", lambda p: "text/plain")
    with pytest.raises(ValueError, match="PDF MIME type requires"):
        ex._validate_type_path(txt, "x.txt", "application/pdf")
    with pytest.raises(ValueError, match="DOCX MIME type requires"):
        ex._validate_type_path(txt, "x.txt", ex.DOCX_MIME_TYPE)

    jsonp = _write(tmp_path, "x.json", b"{}")
    html = _write(tmp_path, "x.html", b"<p>x</p>")
    monkeypatch.setattr(ex, "_detected_mime", lambda p: "application/octet-stream")
    with pytest.raises(ValueError, match="JSON content detected"):
        ex._validate_type_path(jsonp, "x.json", "application/json")
    with pytest.raises(ValueError, match="HTML content detected"):
        ex._validate_type_path(html, "x.html", "text/html")
    with pytest.raises(ValueError, match="text content detected"):
        ex._validate_type_path(txt, "x.txt", "text/plain")


def test_docx_no_text_and_plain_text_empty_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _write(tmp_path, "x.docx", b"PK\x03\x04")
    monkeypatch.setattr(ex, "_validate_type_path", lambda *a: ".docx")
    monkeypatch.setattr(ex, "_docx_body_xml", lambda p: b"<x/>")
    monkeypatch.setattr(ex, "_docx_paragraphs", lambda b: [])
    with pytest.raises(ValueError, match="no extractable text"):
        ex.extract_pages_from_path(p, "x.docx", ex.DOCX_MIME_TYPE, False, "eng")

    q = _write(tmp_path, "x.txt", b"   \n")
    monkeypatch.setattr(ex, "_validate_type_path", lambda *a: ".txt")
    with pytest.raises(ValueError, match="no extractable text"):
        ex.extract_pages_from_path(q, "x.txt", "text/plain", False, "eng")


def test_sandbox_worker_return_output_and_response_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _write(tmp_path, "x.txt", b"hello")

    def call(result):
        monkeypatch.setattr(ex.subprocess, "run", lambda *a, **k: result)
        return ex.extract_pages_sandboxed(
            p, "x.txt", "text/plain", False, "eng",
            max_pdf_pages=2, ocr_total_timeout_seconds=2, timeout_seconds=2,
            memory_limit_mb=32, output_limit_bytes=64,
        )

    with pytest.raises(ValueError, match="worker failed"):
        call(SimpleNamespace(returncode=2, stderr="worker failed", stdout=""))
    with pytest.raises(ValueError, match="output exceeds"):
        call(SimpleNamespace(returncode=0, stderr="", stdout="x" * 65))
    with pytest.raises(ValueError, match="invalid parser sandbox response"):
        call(SimpleNamespace(returncode=0, stderr="", stdout="{}"))
    good = '{"pages":[{"page":null,"text":"ok"}],"method":"plain_text"}'
    pages, method = call(SimpleNamespace(returncode=0, stderr="", stdout=good))
    assert pages[0].text == "ok" and method == "plain_text"


def test_docx_archive_bounds_and_body_presence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _write(tmp_path, "x.docx", b"zip")

    class Member:
        def __init__(self, size): self.file_size = size

    class Archive:
        def __init__(self, members, names=None, body=b"<x/>"):
            self.members, self.names, self.body = members, names or [], body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def infolist(self): return self.members
        def namelist(self): return self.names
        def read(self, name): assert name == ex._DOCX_BODY; return self.body

    monkeypatch.setattr(ex.zipfile, "ZipFile", lambda p: Archive([Member(0)] * (ex._DOCX_MAX_MEMBERS + 1)))
    with pytest.raises(ValueError, match="too many members"):
        ex._docx_body_xml(p)
    monkeypatch.setattr(ex.zipfile, "ZipFile", lambda p: Archive([Member(ex._DOCX_MAX_MEMBER_BYTES + 1)]))
    with pytest.raises(ValueError, match="member exceeds"):
        ex._docx_body_xml(p)
    monkeypatch.setattr(ex, "_DOCX_MAX_MEMBER_BYTES", ex._DOCX_MAX_TOTAL_BYTES + 1)
    monkeypatch.setattr(ex.zipfile, "ZipFile", lambda p: Archive([Member(ex._DOCX_MAX_TOTAL_BYTES + 1)]))
    with pytest.raises(ValueError, match="uncompressed size"):
        ex._docx_body_xml(p)
    monkeypatch.setattr(ex.zipfile, "ZipFile", lambda p: Archive([Member(1)], []))
    with pytest.raises(ValueError, match="no word/document.xml"):
        ex._docx_body_xml(p)


def test_docx_xml_control_tokens_and_entity_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = f'''<w:document xmlns:w="{ns}"><w:body><w:p><w:r><w:t>A</w:t><w:tab/><w:t>B</w:t><w:br/><w:t>C</w:t><w:cr/></w:r></w:p><w:p><w:r><w:t>   </w:t></w:r></w:p></w:body></w:document>'''.encode()
    assert ex._docx_paragraphs(xml) == ["A\tB\nC"]

    p = _write(tmp_path, "x.docx", b"zip")
    class A:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def infolist(self): return [SimpleNamespace(file_size=30)]
        def namelist(self): return [ex._DOCX_BODY]
        def read(self, n): return b"<!DOCTYPE x><x/>"
    monkeypatch.setattr(ex.zipfile, "ZipFile", lambda p: A())
    with pytest.raises(ValueError, match="DTD|entity"):
        ex._docx_body_xml(p)


def test_hard_chunks_short_stride_whitespace_and_break() -> None:
    assert ex._hard_chunks("abc", 10, 1) == ["abc"]
    with pytest.raises(ValueError, match="overlap_chars"):
        ex._hard_chunks("abcdefghijk", 5, 5)
    chunks = ex._hard_chunks("abcde     fghij", 6, 1)
    assert chunks and all(ch.strip() for ch in chunks)


def test_make_spans_bounds_empty_and_section_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="max_chars"):
        ex.make_spans([ExtractedPage(page=1, text="x")], max_chars=99)
    with pytest.raises(ValueError, match="overlap_chars"):
        ex.make_spans([ExtractedPage(page=1, text="x")], max_chars=100, overlap_chars=100)
    with pytest.raises(ValueError, match="no evidence"):
        ex.make_spans([ExtractedPage(page=1, text="   ")], max_chars=100, overlap_chars=10)
    text = "Стаття 12\n" + ("word " * 100)
    spans = ex.make_spans([ExtractedPage(page=1, text=text)], max_chars=100, overlap_chars=10, max_spans=20)
    assert len(spans) > 1 and spans[0]["section"] == "Стаття 12"
    with pytest.raises(ValueError, match="maximum span count"):
        ex.make_spans([ExtractedPage(page=1, text=text)], max_chars=100, overlap_chars=10, max_spans=1)


def test_sandbox_limits_with_and_without_nproc(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(ex.resource, "setrlimit", lambda kind, limit: calls.append((kind, limit)))
    ex._sandbox_limits(1, 1, 100)
    assert len(calls) >= 4
