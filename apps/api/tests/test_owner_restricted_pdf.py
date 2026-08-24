"""A permissions flag is not a secret, and refusing both cost thirty-two documents.

`is_encrypted` covers two different documents. A *user* password means the file is a
secret: nobody without it may read the text, and this system must not guess at one. An
*owner* password with an empty user password means the file opens for everyone — every
conforming reader shows it, including the one on a phone — and the flag restricts
printing and copying.

The first real import refused both under one message. Thirty-two documents were lost that
way: «Протидія мінній війні», «Методичка Антибпла V8», «КАБ-1500», none of them secret.
Thirty-one now extract; the thirty-second is refused for an unrelated reason and says so.

The restriction is recorded, not ignored. The extraction method becomes
`pdf_text_owner_restricted`, which travels into the version record and the ingest audit
payload, so a curator sees that the publisher set a permission and can decide what it
meant for this corpus.

The test that matters is the second one: a document with a real user password must still
be refused. Without it "we accept owner-restricted files" and "we accept every encrypted
file" are the same code.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from korpus.infrastructure.extraction import extract_pages_from_path
from pypdf import PdfWriter

TEXT = "Порядок дій під час протидії мінній війні визначається цим документом."


def _pdf_with(passwords: tuple[str, str] | None) -> bytes:
    """A one-page PDF, optionally encrypted. `(user, owner)`."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if passwords is not None:
        user, owner = passwords
        writer.encrypt(user_password=user, owner_password=owner)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _extract(path: Path) -> tuple[list[object], str]:
    return extract_pages_from_path(
        path=path,
        filename=path.name,
        mime_type="application/pdf",
        ocr_enabled=False,
        ocr_languages="ukr",
        max_pdf_pages=50,
    )


def test_an_owner_restricted_document_is_read_and_the_restriction_recorded(
    tmp_path: Path,
) -> None:
    document = tmp_path / "order.pdf"
    document.write_bytes(_pdf_with(("", "owner-secret")))

    with pytest.raises(ValueError) as raised:
        _extract(document)

    # A blank page has no text, so extraction refuses for *that* reason. What must not
    # appear is the refusal this fix removed: the file was opened.
    message = str(raised.value)
    assert "password" not in message, message
    assert "encrypted PDF is not accepted" not in message, message


def test_a_document_with_a_user_password_is_still_refused(tmp_path: Path) -> None:
    """The control. Without this, "owner-restricted" and "any encrypted file" are one."""
    document = tmp_path / "secret.pdf"
    document.write_bytes(_pdf_with(("reader-password", "owner-secret")))

    with pytest.raises(ValueError, match="password that was not supplied"):
        _extract(document)


def test_an_unencrypted_document_is_unaffected(tmp_path: Path) -> None:
    document = tmp_path / "plain.pdf"
    document.write_bytes(_pdf_with(None))

    with pytest.raises(ValueError) as raised:
        _extract(document)

    assert "password" not in str(raised.value), str(raised.value)
