"""Preserve Word body blocks and lossless cell boundaries in canonical text."""

from __future__ import annotations

import json
from collections.abc import Iterator
from xml.etree import ElementTree

WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_AMBIGUOUS_GRID = frozenset(
    {f"{WORD}{name}" for name in ("vMerge", "hMerge", "gridBefore", "gridAfter")}
)


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    if any(node.tag == f"{WORD}tbl" for node in paragraph.iter()):
        raise ValueError("DOCX table embedded in a paragraph is unsupported")
    pieces: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{WORD}t" and node.text:
            pieces.append(node.text)
        elif node.tag == f"{WORD}tab":
            pieces.append("\t")
        elif node.tag in {f"{WORD}br", f"{WORD}cr"}:
            pieces.append("\n")
    return "".join(pieces).strip()


def _direct_children(node: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    children = node.findall(f"{WORD}{name}")
    if len(children) != sum(1 for _child in node.iter(f"{WORD}{name}")):
        raise ValueError("DOCX wrapped table rows or cells are unsupported")
    return children


def _table_grid(table: ElementTree.Element) -> int | None:
    """Reject unrepresented geometry before exposing any table values."""
    for node in table.iter():
        if node is not table and node.tag == f"{WORD}tbl":
            raise ValueError("DOCX nested table structure is unsupported")
        if node.tag in _AMBIGUOUS_GRID:
            raise ValueError("DOCX merged or omitted table cells are unsupported")
        if node.tag == f"{WORD}gridSpan" and node.get(f"{WORD}val") != "1":
            raise ValueError("DOCX merged table cells are unsupported")
    grid = table.find(f"{WORD}tblGrid")
    return len(grid.findall(f"{WORD}gridCol")) if grid is not None else None


def _table_rows(table: ElementTree.Element) -> list[list[str]]:
    width = _table_grid(table)
    rows: list[list[str]] = []
    for row in _direct_children(table, "tr"):
        cells = [
            "\n\n".join(_paragraph_text(paragraph) for paragraph in cell.iter(f"{WORD}p"))
            for cell in _direct_children(row, "tc")
        ]
        if width is None:
            width = len(cells)
        if not cells or len(cells) != width:
            raise ValueError("DOCX table row does not match its column grid")
        rows.append(cells)
    if not rows:
        raise ValueError("DOCX table contains no rows")
    return rows


def _blocks(root: ElementTree.Element) -> Iterator[ElementTree.Element]:
    """Visit body blocks in order without recursively flattening table cells."""
    pending = [root]
    while pending:
        node = pending.pop()
        if node.tag in {f"{WORD}p", f"{WORD}tbl"}:
            yield node
        else:
            pending.extend(reversed(list(node)))


def _encode_cell(cell: str) -> str:
    encoded = json.dumps(cell, ensure_ascii=False).replace("  ", "\\u0020\\u0020")
    # JSON escapes ASCII control characters. Escape the remaining splitlines()
    # separators too, while retaining ordinary Unicode words for retrieval.
    return encoded.translate({0x85: "\\u0085", 0x2028: "\\u2028", 0x2029: "\\u2029"})


def extract_docx_blocks(body: bytes) -> list[str]:
    """Tables use JSON-quoted TSV: empty cells and internal newlines remain explicit.

    Cell quoting is structural encoding, not inferred content. Every cell can be
    decoded independently, including literal quotes, tabs, backslashes and newlines.
    The outer normalizer cannot trim a trailing empty cell because it is encoded as
    two quotes. Existing whitespace-column quality checks still see each delimiter.
    """
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ValueError("DOCX body is not well-formed XML") from exc
    blocks: list[str] = []
    for node in _blocks(root):
        if node.tag == f"{WORD}tbl":
            rows = _table_rows(node)
            blocks.append("\n".join("\t".join(_encode_cell(cell) for cell in row) for row in rows))
        else:
            text = _paragraph_text(node)
            if text:
                blocks.append(text)
    return blocks
