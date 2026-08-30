"""Content-type confusion at the upload boundary, and the chunker's own invariants.

`_validate_type_path` is the check that decides which parser a file reaches. Its
comment states the property: a renamed archive does not get to choose its own reader.
Three signals have to agree — extension, declared MIME and the first bytes — and where
a system detector is available, its verdict too.

Measured on 2026-08-28 the JSON, HTML and plain-text detector branches had never been
taken, and neither had the chunker's stride guard. A detector whose disagreement is
never tested is a detector whose result can be dropped without any test noticing, and
the file that follows is then parsed as whatever it claims to be.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from korpus.infrastructure.extraction import _hard_chunks, _validate_type_path


def _write(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("order.exe", "unsupported file extension"),
        ("order", "unsupported file extension"),
        ("order.doc", "unsupported file extension"),
        ("order.zip", "unsupported file extension"),
    ],
)
def test_an_extension_outside_the_supported_set_is_refused(
    tmp_path: Path, name: str, message: str
) -> None:
    path = _write(tmp_path, name, b"whatever")
    with pytest.raises(ValueError, match=message):
        _validate_type_path(path, name, "text/plain")


def test_a_mime_type_outside_the_supported_set_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "order.txt", b"text")
    with pytest.raises(ValueError, match="unsupported MIME type"):
        _validate_type_path(path, "order.txt", "application/x-msdownload")


@pytest.mark.parametrize(
    ("name", "content", "mime", "message"),
    [
        ("order.pdf", b"not a pdf at all", "application/pdf", "file signature"),
        ("order.docx", b"not a zip at all", "application/octet-stream", "file signature"),
    ],
)
def test_an_extension_that_the_first_bytes_contradict_is_refused(
    tmp_path: Path, name: str, content: bytes, mime: str, message: str
) -> None:
    """The magic bytes are read before any parser is chosen."""
    path = _write(tmp_path, name, content)
    with pytest.raises(ValueError, match=message):
        _validate_type_path(path, name, mime)


@pytest.mark.parametrize(
    ("name", "mime", "message"),
    [
        ("order.pdf", "text/plain", "does not match MIME type"),
        ("order.txt", "application/pdf", "PDF MIME type requires .pdf"),
        (
            "order.txt",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "DOCX MIME type requires .docx",
        ),
    ],
)
def test_a_declared_mime_type_that_the_extension_contradicts_is_refused(
    tmp_path: Path, name: str, mime: str, message: str
) -> None:
    path = _write(tmp_path, name, b"%PDF-1.7\n" if name.endswith(".pdf") else b"plain text")
    with pytest.raises(ValueError, match=message):
        _validate_type_path(path, name, mime)


@pytest.mark.parametrize(
    ("name", "detected", "message"),
    [
        ("order.json", "application/pdf", "JSON content detected as"),
        ("order.json", "application/zip", "JSON content detected as"),
        ("order.html", "application/pdf", "HTML content detected as"),
        ("order.htm", "image/png", "HTML content detected as"),
        ("order.txt", "application/pdf", "text content detected as"),
        ("order.md", "application/octet-stream", "text content detected as"),
    ],
)
def test_a_detector_verdict_that_contradicts_the_extension_is_refused(
    tmp_path: Path, name: str, detected: str, message: str
) -> None:
    """The declared type and the extension can both be attacker-controlled; this is not.

    Only the system detector reads the bytes themselves, so it is the one signal an
    uploader cannot simply assert.
    """
    path = _write(tmp_path, name, b"content that claims nothing")
    with (
        patch("korpus.infrastructure.extraction._detected_mime", return_value=detected),
        pytest.raises(ValueError, match=message),
    ):
        _validate_type_path(path, name, "text/plain")


@pytest.mark.parametrize(
    ("name", "detected"),
    [
        ("order.json", "application/json"),
        ("order.json", "text/plain"),
        ("order.html", "text/html"),
        ("order.txt", "text/plain"),
        ("order.md", "text/markdown"),
    ],
)
def test_a_detector_verdict_that_agrees_admits_the_file(
    tmp_path: Path, name: str, detected: str
) -> None:
    """The dual. Refusing every combination would satisfy the assertions above."""
    path = _write(tmp_path, name, b"content")
    with patch("korpus.infrastructure.extraction._detected_mime", return_value=detected):
        assert _validate_type_path(path, name, "text/plain") == Path(name).suffix


def test_an_absent_detector_does_not_block_ingestion(tmp_path: Path) -> None:
    """`file(1)` is not guaranteed to exist; its absence is not a verdict of its own."""
    path = _write(tmp_path, "order.txt", b"content")
    with patch("korpus.infrastructure.extraction._detected_mime", return_value=None):
        assert _validate_type_path(path, "order.txt", "text/plain") == ".txt"


def test_an_overlap_that_is_not_smaller_than_the_window_would_never_advance(
    tmp_path: Path,
) -> None:
    """Stride is window minus overlap; at zero or below the loop cannot move forward.

    Without this guard the call does not fail — it hangs, emitting the same chunk until
    memory runs out, which is a far worse failure than a rejected argument.
    """
    text = "a" * 500
    for overlap in (100, 150):
        with pytest.raises(ValueError, match="overlap_chars must be smaller"):
            _hard_chunks(text, 100, overlap)


def test_a_window_wider_than_the_text_yields_one_chunk() -> None:
    assert _hard_chunks("short", 100, 10) == ["short"]


def test_whitespace_only_windows_are_dropped_rather_than_emitted() -> None:
    """A chunk of spaces carries no evidence and would still consume a span slot."""
    text = "alpha" + " " * 40 + "omega"
    chunks = _hard_chunks(text, 10, 2)
    assert chunks
    assert all(chunk.strip() for chunk in chunks)
    assert "alpha" in chunks[0]
    assert any("omega" in chunk for chunk in chunks)


def test_html_that_the_detector_calls_javascript_is_admitted_when_it_opens_as_html(
    tmp_path: Path,
) -> None:
    """Виміряно 2026-08-30: обидві сторінки, які екстрактор відхилив як «HTML content
    detected as application/javascript», віддають HTTP 200, text/html і 13 633 та 2 321
    слово справжнього тексту. `file` каже про них «JavaScript source, with very long
    lines» — нюхача збиває довгий рядок вбудованого скрипту, а в одній із них цей скрипт
    стоїть найпершим у `<head>`. Одна зі сторінок — офіційна позиція НАТО щодо РФ."""
    page = (
        b"<!DOCTYPE html>\n<html><head><script>"
        + b"x=1;" * 400
        + "</script></head><body>текст</body></html>".encode()
    )
    path = _write(tmp_path, "page.html", page)
    with patch(
        "korpus.infrastructure.extraction._detected_mime", return_value="application/javascript"
    ):
        assert _validate_type_path(path, "page.html", "text/html") == ".html"


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("renamed.html", b"%PDF-1.7\n" + b"0" * 200),
        ("renamed.html", b"PK\x03\x04" + b"0" * 200),
        ("script.html", b"(function(){var x=1;})();\n" * 40),
        ("empty.html", b""),
        # Розмітка, але не на початку: сторінка, що починається скриптом БЕЗ `<!doctype`,
        # не доводить, що вона HTML — «схоже на HTML» не сміє скасовувати вирок.
        ("late.html", b"var x = 1;\n" * 50 + b"<!DOCTYPE html><html></html>"),
    ],
)
def test_the_markup_check_does_not_admit_anything_that_is_not_html(
    tmp_path: Path, name: str, content: bytes
) -> None:
    """Негативний контроль на саме послаблення: структурна перевірка мусить пропускати
    ЛИШЕ те, що справді відкривається як розмітка. Перейменований PDF, перейменований
    ZIP, справжній скрипт і порожній файл і далі відхиляються."""
    path = _write(tmp_path, name, content)
    with (
        patch(
            "korpus.infrastructure.extraction._detected_mime",
            return_value="application/javascript",
        ),
        pytest.raises(ValueError, match="HTML content detected as"),
    ):
        _validate_type_path(path, name, "text/html")


def test_a_byte_order_mark_does_not_hide_the_markup(tmp_path: Path) -> None:
    """`lstrip()` не бачить `\\xef\\xbb\\xbf`, тож той самий документ, збережений із BOM,
    читався б як не-HTML — хибне відхилення всередині виправлення хибного відхилення."""
    page = "\ufeff  <!DOCTYPE html>\n<html><body>текст</body></html>".encode()
    path = _write(tmp_path, "bom.html", page)
    with patch(
        "korpus.infrastructure.extraction._detected_mime", return_value="application/javascript"
    ):
        assert _validate_type_path(path, "bom.html", "text/html") == ".html"


def test_the_markup_must_appear_in_the_first_kilobyte(tmp_path: Path) -> None:
    """Вікно — це частина правила, а не оптимізація.

    Розмітка за двома кілобайтами пробілів не робить файл документом, що ВІДКРИВАЄТЬСЯ
    як HTML: та сама конструкція дозволила б сховати перед нею що завгодно. Без цієї
    проби константу можна було б підняти до розміру файлу й нічого б не впало — тобто
    вікно не перевірялося б узагалі.
    """
    page = b" " * 2000 + b"<!DOCTYPE html><html><body>text</body></html>"
    path = _write(tmp_path, "padded.html", page)
    with (
        patch(
            "korpus.infrastructure.extraction._detected_mime",
            return_value="application/javascript",
        ),
        pytest.raises(ValueError, match="HTML content detected as"),
    ):
        _validate_type_path(path, "padded.html", "text/html")


def test_a_pdf_that_only_opens_leniently_is_read_and_marked(tmp_path: Path) -> None:
    """Терпимість записується, а не ховається.

    `DD Form 1380` (картка тактичної допомоги пораненому) падала з `malformed PDF page
    tree`: файл зашифрований порожнім паролем, і розшифрування впиралось у `Invalid
    padding bytes`, яку сама pypdf зі `strict=False` ігнорує. Просто зняти `strict`
    означало б послабити читання для ВСІХ файлів мовчки; тому дві спроби і третій стан у
    режимі витягу.
    """
    from korpus.infrastructure.pdf_extraction import _open_pdf

    calls: list[bool] = []

    class _Reader:
        is_encrypted = False

        def __init__(self, _path: str, strict: bool = True) -> None:
            calls.append(strict)
            if strict:
                raise ValueError("Invalid padding bytes")

        @property
        def pages(self) -> list[object]:
            return [object(), object()]

    _reader, _owner, lenient = _open_pdf(tmp_path / "x.pdf", 100, _Reader)
    assert calls == [True, False], "строга спроба мусить бути першою"
    assert lenient is True, "терпимість не позначена — запис не скаже, що файл нестандартний"


def test_a_clean_pdf_is_not_marked_lenient(tmp_path: Path) -> None:
    """Дуальність: файл, що відкривається строго, не сміє отримати позначку."""
    from korpus.infrastructure.pdf_extraction import _open_pdf

    class _Reader:
        is_encrypted = False

        def __init__(self, _path: str, strict: bool = True) -> None:
            pass

        @property
        def pages(self) -> list[object]:
            return [object()]

    _reader, _owner, lenient = _open_pdf(tmp_path / "x.pdf", 100, _Reader)
    assert lenient is False


def test_the_page_ceiling_is_not_bypassed_by_the_lenient_retry(tmp_path: Path) -> None:
    """Ліміт сторінок перевіряється в ОБОХ спробах.

    Інакше послаблення читання тихо послабило б і запобіжник від вичерпання пам'яті:
    файл, що не відкрився строго, обходив би стелю через терпиму гілку.
    """
    from korpus.infrastructure.pdf_extraction import _open_pdf

    class _Reader:
        is_encrypted = False

        def __init__(self, _path: str, strict: bool = True) -> None:
            pass

        @property
        def pages(self) -> list[object]:
            return [object()] * 5000

    with pytest.raises(ValueError, match="page count exceeds"):
        _open_pdf(tmp_path / "x.pdf", 100, _Reader)
