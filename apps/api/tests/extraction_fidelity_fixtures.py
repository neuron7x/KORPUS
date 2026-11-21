"""Tiny neutral archive documents built with locked pypdf and the standard library."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
COVER = (
    "Archive record A01. This reference page records the color samples retained in "
    "the neutral archive for repeatable extraction checks."
)
SCAN_TEXT = "BLUE"


def _scan_bitmap() -> tuple[int, int, bytes]:
    """Visible BLUE glyphs, not a metadata string masquerading as a scanned page."""
    glyphs = (
        ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
        ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
        ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
        ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    )
    rows = ["00" + "00".join(glyph[row] for glyph in glyphs) + "00" for row in range(7)]
    rows = ["0" * len(rows[0]), *rows, "0" * len(rows[0])]
    pixels = bytes(
        channel for row in rows for pixel in row for channel in [0 if pixel == "1" else 255] * 3
    )
    return len(rows[0]), len(rows), pixels


def archive_pdf(pages: tuple[tuple[str, str], ...]) -> bytes:
    """Each page has optional embedded text and image, vector, or blank content."""
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    width, height, pixels = _scan_bitmap()
    scan = DecodedStreamObject()
    scan.set_data(pixels)
    scan.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(width),
            NameObject("/Height"): NumberObject(height),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    image = writer._add_object(scan)
    for text, painting in pages:
        page = writer.add_blank_page(width=900, height=300)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
                NameObject("/XObject"): DictionaryObject({NameObject("/Scan"): image}),
            }
        )
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        operators = f"BT /F1 10 Tf 20 240 Td ({escaped}) Tj ET\n" if text else ""
        if painting == "image":
            operators += "q 150 0 0 45 20 100 cm /Scan Do Q\n"
        elif painting == "vector":
            operators += "20 20 100 100 re f\n"
        elif painting == "state-only":
            operators += "q 1 0 0 1 0 0 cm Q\n"
        elif painting != "blank":
            raise ValueError("unknown fixture painting")
        if operators:
            stream = DecodedStreamObject()
            stream.set_data(operators.encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


def paragraph(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def archive_annotation_pdf(header: str) -> bytes:
    """A real visible annotation appearance, independent of page content streams."""
    writer = PdfWriter()
    writer.clone_document_from_reader(
        PdfReader(io.BytesIO(archive_pdf(((COVER, "blank"), (header, "blank")))))
    )
    appearance = DecodedStreamObject()
    appearance.set_data(b"BT /F1 28 Tf 10 40 Td (BLUE ARCHIVE CARD) Tj ET")
    appearance.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject([NumberObject(x) for x in (0, 0, 400, 100)]),
            NameObject("/Resources"): writer.pages[1]["/Resources"],
        }
    )
    annotation = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/FreeText"),
            NameObject("/Rect"): ArrayObject([NumberObject(x) for x in (20, 100, 420, 200)]),
            NameObject("/F"): NumberObject(4),
            NameObject("/Contents"): TextStringObject("BLUE ARCHIVE CARD"),
            NameObject("/DA"): TextStringObject("/F1 28 Tf 0 g"),
            NameObject("/AP"): DictionaryObject({NameObject("/N"): writer._add_object(appearance)}),
        }
    )
    writer.pages[1][NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def table(rows: list[list[str]], *, grid: bool = True) -> str:
    columns = (
        "<w:tblGrid>" + '<w:gridCol w:w="1800"/>' * len(rows[0]) + "</w:tblGrid>" if grid else ""
    )
    body = "".join(
        "<w:tr>" + "".join("<w:tc>" + paragraph(cell) + "</w:tc>" for cell in row) + "</w:tr>"
        for row in rows
    )
    return "<w:tbl>" + columns + body + "</w:tbl>"


def archive_docx(blocks: str) -> bytes:
    """Minimal OPC Word document; headers and values are supplied explicitly."""
    document = f'<w:document xmlns:w="{WORD_NS}"><w:body>{blocks}<w:sectPr/></w:body></w:document>'
    content_types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in (
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", relationships),
            ("word/document.xml", document),
        ):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, value.encode("utf-8"))
    return result.getvalue()
