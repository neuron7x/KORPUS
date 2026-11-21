"""Real OOXML row/cell boundaries survive extraction, normalization and spans."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from korpus.infrastructure.extraction import (
    DOCX_MIME_TYPE,
    extract_pages_from_path,
    extract_pages_sandboxed,
    make_spans,
)

from apps.api.tests.extraction_fidelity_fixtures import archive_docx, paragraph, table

ROWS = [
    ["ID", "Color", "Count"],
    ["A01", "red", "10"],
    ["B02", "", "20"],
    ["C03", "blue", ""],
    ["", "", ""],
]


def _extract(tmp_path: Path, blocks: str, *, sandboxed: bool = False):
    path = tmp_path / "archive.docx"
    path.write_bytes(archive_docx(blocks))
    arguments = (path, path.name, DOCX_MIME_TYPE, False, "eng")
    if sandboxed:
        return extract_pages_sandboxed(
            *arguments,
            max_pdf_pages=4,
            ocr_total_timeout_seconds=10,
            timeout_seconds=10,
            memory_limit_mb=512,
            output_limit_bytes=32_768,
        )
    return extract_pages_from_path(*arguments)


def _decode(block: str) -> list[list[str]]:
    return [[json.loads(cell) for cell in row.split("\t")] for row in block.splitlines()]


@pytest.mark.parametrize("sandboxed", [False, True], ids=["direct", "worker"])
def test_table_rows_headers_and_empty_cells_are_preserved(tmp_path: Path, sandboxed: bool) -> None:
    block = table(ROWS).replace("<w:tr>", "<w:tr><w:trPr><w:tblHeader/></w:trPr>", 1)
    pages, method = _extract(tmp_path, block, sandboxed=sandboxed)

    assert method == "docx_text"
    assert len(pages) == 1 and pages[0].page is None
    assert _decode(pages[0].text) == ROWS
    header, *values = _decode(pages[0].text)
    assert dict(zip(header, values[1], strict=True)) == {"ID": "B02", "Color": "", "Count": "20"}
    assert dict(zip(header, values[2], strict=True)) == {"ID": "C03", "Color": "blue", "Count": ""}
    assert pages[0].text.endswith('""\t""\t""')


@pytest.mark.parametrize("grid", [False, True], ids=["implicit-grid", "explicit-grid"])
def test_standard_tables_and_paragraphs_keep_document_block_order(
    tmp_path: Path, grid: bool
) -> None:
    first, second = [["Name", "Value"], ["A", "red"]], [["Name", "Value"], ["B", "blue"]]
    body = (
        paragraph("Archive introduction.")
        + table(first, grid=grid)
        + paragraph("Second inventory.")
        + table(second, grid=grid)
        + paragraph("Archive end.")
    )

    pages, _method = _extract(tmp_path, body)
    blocks = pages[0].text.split("\n\n")

    assert blocks[0] == "Archive introduction."
    assert _decode(blocks[1]) == first
    assert blocks[2] == "Second inventory."
    assert _decode(blocks[3]) == second
    assert blocks[4] == "Archive end."


def test_quoted_cells_cannot_forge_row_or_column_boundaries(tmp_path: Path) -> None:
    rows = [["Key", "Value", "Empty"], ["A01", 'blue\tred\nnext "label" \\ path  two   three', ""]]
    pages, _method = _extract(tmp_path, table(rows))

    assert _decode(pages[0].text) == rows
    assert len(pages[0].text.splitlines()) == 2
    assert all(len(row.split("\t")) == 3 for row in pages[0].text.splitlines())
    assert pages[0].text.endswith('\t""')


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_unicode_line_separators_stay_inside_their_original_cell(
    tmp_path: Path, separator: str
) -> None:
    rows = [["Key", "Value", "Empty"], ["A01", "синій" + separator + "зелений", ""]]
    pages, _method = _extract(tmp_path, table(rows))
    assert _decode(pages[0].text) == rows
    assert len(pages[0].text.splitlines()) == 2
    assert "синій" in pages[0].text
    assert separator not in pages[0].text


@pytest.mark.parametrize("sandboxed", [False, True], ids=["direct", "worker"])
def test_table_inside_a_textbox_cannot_bypass_table_structure_checks(
    tmp_path: Path, sandboxed: bool
) -> None:
    block = (
        '<w:p><w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml">'
        "<v:textbox><w:txbxContent>"
        + table(ROWS)
        + "</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>"
    )
    with pytest.raises(ValueError, match="embedded in a paragraph"):
        _extract(tmp_path, block, sandboxed=sandboxed)


def test_empty_table_cells_are_structure_and_empty_paragraphs_are_not_facts(tmp_path: Path) -> None:
    rows = [["", "", ""]]
    pages, _method = _extract(tmp_path, paragraph(" ") + table(rows) + paragraph(""))

    assert _decode(pages[0].text) == rows
    assert "None" not in pages[0].text
    assert "null" not in pages[0].text


def test_spans_keep_trailing_empty_cells_and_exact_table_substrings(tmp_path: Path) -> None:
    rows = [["ID", "Color", "Count"], *[[f"A{index:02}", "blue", ""] for index in range(10)]]
    pages, _method = _extract(tmp_path, table(rows))
    spans = make_spans(pages, max_chars=100, overlap_chars=30)

    assert len(spans) > 1
    assert all(span["text"] in pages[0].text for span in spans)
    assert _decode(pages[0].text) == rows
    for row in pages[0].text.splitlines():
        assert any(row in span["text"] for span in spans), row


@pytest.mark.parametrize(
    "property_xml",
    [
        '<w:gridSpan w:val="2"/>',
        "<w:gridSpan/>",
        '<w:vMerge w:val="restart"/>',
        "<w:vMerge/>",
        '<w:hMerge w:val="restart"/>',
        '<w:gridBefore w:val="1"/>',
        '<w:gridAfter w:val="1"/>',
    ],
)
def test_merged_or_omitted_cells_are_explicitly_unsupported(
    tmp_path: Path, property_xml: str
) -> None:
    body = table(ROWS).replace("<w:tc>", f"<w:tc><w:tcPr>{property_xml}</w:tcPr>", 1)

    with pytest.raises(ValueError, match=r"merged|omitted"):
        _extract(tmp_path, body)


def test_unit_grid_span_does_not_reject_an_ordinary_cell(tmp_path: Path) -> None:
    body = table(ROWS).replace("<w:tc>", '<w:tc><w:tcPr><w:gridSpan w:val="1"/></w:tcPr>', 1)
    pages, _method = _extract(tmp_path, body)
    assert _decode(pages[0].text) == ROWS


def test_nested_table_is_explicitly_unsupported(tmp_path: Path) -> None:
    body = table(ROWS).replace("<w:tc>", "<w:tc>" + table([["Inner", "value"]]), 1)

    with pytest.raises(ValueError, match="nested table"):
        _extract(tmp_path, body)


@pytest.mark.parametrize("tag", ["tr", "tc"], ids=["wrapped-row", "wrapped-cell"])
def test_wrapped_table_geometry_cannot_silently_drop_values(tmp_path: Path, tag: str) -> None:
    body = table(ROWS).replace(f"<w:{tag}>", f"<w:sdt><w:sdtContent><w:{tag}>", 1)
    body = body.replace(f"</w:{tag}>", f"</w:{tag}></w:sdtContent></w:sdt>", 1)

    with pytest.raises(ValueError, match="wrapped table"):
        _extract(tmp_path, body)


@pytest.mark.parametrize("last", [["A01", "red"], ["A01", "red", "10", "extra"], []])
def test_ragged_table_grid_is_a_refusal_not_an_inferred_value(
    tmp_path: Path, last: list[str]
) -> None:
    with pytest.raises(ValueError, match="does not match its column grid"):
        _extract(tmp_path, table([ROWS[0], last]))


def test_table_without_rows_and_malformed_xml_are_refused(tmp_path: Path) -> None:
    for body, message in (("<w:tbl/>", "no rows"), ("<w:p>", "well-formed XML")):
        with pytest.raises(ValueError, match=message):
            _extract(tmp_path, body)


def test_cell_paragraph_breaks_are_escaped_without_reordering(tmp_path: Path) -> None:
    body = table([["ID", "Notes"], ["A01", "first"]]).replace(
        paragraph("first"), paragraph("first") + paragraph("second")
    )
    pages, _method = _extract(tmp_path, body)
    assert _decode(pages[0].text) == [["ID", "Notes"], ["A01", "first\n\nsecond"]]


def test_table_serialization_remains_bounded_by_worker_output_limit(tmp_path: Path) -> None:
    path = tmp_path / "archive.docx"
    path.write_bytes(archive_docx(table([["ID", "Notes"], ["A01", "blue " * 200]])))

    with pytest.raises(ValueError, match=r"output.*limit"):
        extract_pages_sandboxed(
            path,
            path.name,
            DOCX_MIME_TYPE,
            False,
            "eng",
            max_pdf_pages=4,
            ocr_total_timeout_seconds=10,
            timeout_seconds=10,
            memory_limit_mb=512,
            output_limit_bytes=64,
        )
