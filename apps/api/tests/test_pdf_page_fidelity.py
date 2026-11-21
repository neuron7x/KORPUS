"""Real mixed PDF bytes must not turn missing pages into a successful extraction.

OCR return values and process routing are controlled separately from PDF parsing.
These tests establish bounded completeness detection, not a native OCR accuracy score.
"""

from __future__ import annotations

import io
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from korpus.domain.models import ExtractedPage
from korpus.infrastructure import extraction, pdf_extraction, pdf_ocr
from pypdf import PdfReader

from apps.api.tests.extraction_fidelity_fixtures import (
    COVER,
    SCAN_TEXT,
    archive_annotation_pdf,
    archive_pdf,
)


def _extract(path: Path, *, enabled: bool = False, sandboxed: bool = False):
    arguments = (path, path.name, "application/pdf", enabled, "eng")
    if sandboxed:
        return extraction.extract_pages_sandboxed(
            *arguments,
            max_pdf_pages=4,
            ocr_total_timeout_seconds=10,
            timeout_seconds=10,
            memory_limit_mb=512,
            output_limit_bytes=32_768,
        )
    return extraction.extract_pages_from_path(*arguments, max_pdf_pages=4)


@pytest.mark.parametrize("sandboxed", [False, True], ids=["direct", "worker"])
@pytest.mark.parametrize("header", ["", COVER], ids=["scan-page", "header-and-scan"])
def test_unextracted_raster_page_is_never_accepted_as_complete(
    tmp_path: Path, sandboxed: bool, header: str
) -> None:
    document = archive_pdf(((COVER, "blank"), (header, "image")))
    reader = PdfReader(io.BytesIO(document), strict=True)
    assert reader.pages[0].extract_text() == COVER
    assert reader.pages[1].extract_text().strip() == header
    assert reader.pages[1]["/Resources"]["/XObject"]["/Scan"]["/Subtype"] == "/Image"
    path = tmp_path / "archive.pdf"
    path.write_bytes(document)

    with pytest.raises(ValueError, match=r"pages \(2,\).*OCR is disabled"):
        _extract(path, sandboxed=sandboxed)


@pytest.mark.parametrize("sandboxed", [False, True], ids=["direct", "worker"])
@pytest.mark.parametrize("enabled", [False, True], ids=["no-ocr", "ocr"])
@pytest.mark.parametrize("header", ["", "Archive annotation page."], ids=["no-header", "header"])
def test_visible_annotation_appearance_is_refused_before_successful_page_extraction(
    tmp_path: Path, sandboxed: bool, enabled: bool, header: str
) -> None:
    control = tmp_path / "control.pdf"
    control.write_bytes(archive_pdf(((COVER, "blank"), (header, "blank"))))
    pages, method = _extract(control, enabled=enabled, sandboxed=sandboxed)
    assert [(page.page, page.text) for page in pages] == [(1, COVER), (2, header)]
    assert method == "pdf_text"
    path = tmp_path / "annotation.pdf"
    path.write_bytes(archive_annotation_pdf(header))
    reader = PdfReader(path, strict=True)
    assert reader.pages[1].extract_text().strip() == header
    annotation = reader.pages[1]["/Annots"][0].get_object()
    assert b"BLUE ARCHIVE CARD" in annotation["/AP"]["/N"].get_data()

    with pytest.raises(ValueError, match="annotation appearance is unsupported"):
        _extract(path, enabled=enabled, sandboxed=sandboxed)


@pytest.mark.parametrize("header", ["", COVER], ids=["scan-page", "header-and-scan"])
def test_only_incomplete_pages_use_ocr_and_native_pages_remain_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, header: str
) -> None:
    path = tmp_path / "archive.pdf"
    path.write_bytes(archive_pdf(((COVER, "blank"), (header, "image"), ("", "blank"))))
    observed: list[tuple[int, ...]] = []
    recognized = f"{header}\n{SCAN_TEXT}".strip()

    def ocr(*args, page_numbers, **kwargs):
        observed.append(page_numbers)
        return [ExtractedPage(page=2, text=recognized)]

    monkeypatch.setattr(pdf_extraction, "_ocr_pages", ocr)
    pages, method = _extract(path, enabled=True)

    assert observed == [(2,)]
    assert [(page.page, page.text) for page in pages] == [(1, COVER), (2, recognized), (3, "")]
    assert method == "pdf_ocr_mixed"


@pytest.mark.parametrize("painting", ["blank", "state-only"])
def test_genuine_blank_pages_are_retained_without_ocr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, painting: str
) -> None:
    path = tmp_path / "archive.pdf"
    path.write_bytes(archive_pdf(((COVER, "blank"), ("", painting))))
    monkeypatch.setattr(pdf_extraction, "_ocr_pages", lambda *a, **k: pytest.fail("blank page OCR"))

    pages, method = _extract(path, enabled=True)

    assert [(page.page, page.text) for page in pages] == [(1, COVER), (2, "")]
    assert method == "pdf_text"


def test_visible_vector_content_without_text_is_explicitly_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "archive.pdf"
    path.write_bytes(archive_pdf(((COVER, "blank"), ("", "vector"))))

    with pytest.raises(ValueError, match="OCR is disabled"):
        _extract(path)


@pytest.mark.parametrize(
    "recognized",
    ["", "   ", SCAN_TEXT, COVER],
    ids=["empty", "whitespace", "header-lost", "header-only"],
)
def test_ocr_cannot_discard_known_embedded_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recognized: str
) -> None:
    path = tmp_path / "archive.pdf"
    path.write_bytes(archive_pdf(((COVER, "image"),)))
    monkeypatch.setattr(
        pdf_extraction, "_ocr_pages", lambda *a, **k: [ExtractedPage(page=1, text=recognized)]
    )

    with pytest.raises(
        ValueError, match=r"OCR produced no text|did not preserve embedded text|added no text"
    ):
        _extract(path, enabled=True)


@pytest.mark.parametrize(
    "ids",
    [(), (1,), (2, 2), (3,), (None,)],
    ids=["none", "wrong", "duplicate", "outside", "missing-id"],
)
def test_incomplete_ocr_inventory_refuses_the_whole_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ids: tuple[int | None, ...]
) -> None:
    path = tmp_path / "archive.pdf"
    path.write_bytes(archive_pdf(((COVER, "blank"), ("", "image"))))
    monkeypatch.setattr(
        pdf_extraction,
        "_ocr_pages",
        lambda *a, **k: [ExtractedPage(page=page, text=SCAN_TEXT) for page in ids],
    )

    with pytest.raises(ValueError, match=r"no text|incomplete page inventory"):
        _extract(path, enabled=True)


def test_page_and_time_caps_refuse_before_ocr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "archive.pdf"
    path.write_bytes(archive_pdf(((COVER, "blank"), ("", "image"))))
    monkeypatch.setattr(
        pdf_extraction, "_ocr_pages", lambda *a, **k: pytest.fail("OCR after refusal")
    )
    for limits, message in (
        ({"max_pdf_pages": 1, "ocr_total_timeout_seconds": 10}, "page count exceeds"),
        ({"max_pdf_pages": 2, "ocr_total_timeout_seconds": 0}, "time budget exceeded"),
    ):
        with pytest.raises(ValueError, match=message):
            extraction.extract_pages_from_path(
                path, path.name, "application/pdf", True, "eng", **limits
            )


def test_worker_output_cap_still_bounds_native_page_content(tmp_path: Path) -> None:
    path = tmp_path / "archive.pdf"
    path.write_bytes(archive_pdf(((COVER, "blank"),)))

    with pytest.raises(ValueError, match=r"output.*limit"):
        extraction.extract_pages_sandboxed(
            path,
            path.name,
            "application/pdf",
            False,
            "eng",
            max_pdf_pages=4,
            ocr_total_timeout_seconds=10,
            timeout_seconds=10,
            memory_limit_mb=512,
            output_limit_bytes=64,
        )


def test_selected_ocr_renderer_keeps_original_page_numbers_and_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    deadline = time.monotonic() + 10

    def run(command, **kwargs):
        calls.append(command)
        assert 0 < kwargs["timeout"] <= 10
        assert kwargs["env"]["LC_ALL"] == "C"
        if command[0] == "pdftoppm":
            assert command[command.index("-f") + 1] == command[command.index("-l") + 1]
            assert "-singlefile" in command
            Path(command[-1]).with_suffix(".png").write_bytes(b"controlled-image")
            return SimpleNamespace(returncode=0)
        assert command[0] == "tesseract"
        return SimpleNamespace(stdout=SCAN_TEXT.encode())

    monkeypatch.setattr(pdf_ocr.subprocess, "run", run)
    pages = pdf_ocr.ocr_pages(
        tmp_path / "archive.pdf", "eng", deadline, 4, str.strip, page_numbers=(2, 4)
    )

    assert [(page.page, page.text) for page in pages] == [(2, SCAN_TEXT), (4, SCAN_TEXT)]
    renders = [command for command in calls if command[0] == "pdftoppm"]
    assert [command[command.index("-f") + 1] for command in renders] == ["2", "4"]
    assert len(calls) == 4


@pytest.mark.parametrize("selection", [(), (2, 1), (1, 1), (0,), (5,), (True,)])
def test_invalid_ocr_page_selection_never_spawns_a_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selection: tuple[int, ...]
) -> None:
    monkeypatch.setattr(pdf_ocr.subprocess, "run", lambda *a, **k: pytest.fail("invalid selection"))

    with pytest.raises(ValueError, match="page selection is invalid"):
        pdf_ocr.ocr_pages(
            tmp_path / "archive.pdf", "eng", time.monotonic() + 10, 4, str, page_numbers=selection
        )


@pytest.mark.parametrize("extra", [False, True], ids=["missing-image", "extra-image"])
def test_renderer_inventory_must_match_selected_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: bool
) -> None:
    def run(command, **kwargs):
        assert command[0] == "pdftoppm", "incomplete rendering must not reach OCR"
        if extra:
            Path(command[-1]).with_suffix(".png").write_bytes(b"image")
            Path(command[-1]).parent.joinpath("unexpected.png").write_bytes(b"image")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(pdf_ocr.subprocess, "run", run)
    with pytest.raises(ValueError, match="incomplete page inventory"):
        pdf_ocr.ocr_pages(
            tmp_path / "archive.pdf", "eng", time.monotonic() + 10, 4, str, page_numbers=(2,)
        )


def test_ocr_subprocess_timeout_is_a_document_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "archive.pdf"
    path.write_bytes(archive_pdf((("", "image"),)))

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("controlled-ocr", 1)

    monkeypatch.setattr(pdf_extraction, "_ocr_pages", timeout)
    with pytest.raises(ValueError, match="OCR execution failed"):
        _extract(path, enabled=True)
