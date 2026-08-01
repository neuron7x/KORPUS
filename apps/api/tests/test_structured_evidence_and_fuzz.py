from __future__ import annotations

import os
import random
import time
from pathlib import Path

import pytest

from apps.api.tests.helpers import approve, ingest_text
from korpus.application.evidence import contradiction_reason, segment_sentences
from korpus.infrastructure import extraction


def test_numbers_units_tables_and_formulae_remain_citable(client):
    text = (
        "Порогова температура становить 37,5 °C.\n\n"
        "| Параметр | Значення |\n| Тиск | 120 кПа |\n\n"
        "Формула сили: F = m·a."
    )
    result = ingest_text(client, text=text)
    approve(client, result["version"]["id"])
    temperature = client.post("/v1/answers", json={"text": "Яка порогова температура?"}).json()
    assert temperature["status"] == "answered"
    assert any("37,5 °C" in item["quote"] for item in temperature["citations"])
    formula = client.post("/v1/answers", json={"text": "Яка формула сили?"}).json()
    assert formula["status"] == "answered"
    assert any("F = m·a" in item["quote"] for item in formula["citations"])


def test_sentence_offsets_preserve_decimals_abbreviations_and_rows():
    text = "Пункт 3.5 діє. Див. табл. 2.\n1) Значення 120 кПа.\n2) Температура 37,5 °C."
    segments = segment_sentences(text)
    assert all(text[start:end] == sentence for sentence, start, end in segments)
    assert any("3.5" in sentence for sentence, _, _ in segments)
    assert any("120 кПа" in sentence for sentence, _, _ in segments)
    assert any("37,5 °C" in sentence for sentence, _, _ in segments)


def test_numeric_unit_conflicts_are_detected_without_cross_unit_false_positive():
    assert contradiction_reason("Тиск має бути 120 кПа.", "Тиск має бути 140 кПа.") == "numeric_conflict:кпа"
    assert contradiction_reason("Відстань 120 м.", "Відстань 120 км.") is None


def test_text_html_json_parser_seeded_fuzz_is_bounded(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(extraction, "_detected_mime", lambda path: "text/plain")
    source = random.Random(20260801)
    started = time.monotonic()
    for index in range(120):
        suffix, mime = source.choice([
            (".txt", "text/plain"), (".md", "text/markdown"), (".json", "application/json"),
            (".html", "text/html"),
        ])
        path = tmp_path / f"fuzz-{index}{suffix}"
        if suffix == ".json":
            payload = ("{\"value\":\"" + "x" * source.randint(0, 200) + "\"}").encode()
        elif suffix == ".html":
            payload = ("<div>visible<script>secret()</script>" + "<b>" * source.randint(0, 20) + "tail").encode()
        else:
            payload = os.urandom(source.randint(1, 128)) if index % 7 == 0 else ("дані " * source.randint(1, 80)).encode()
        path.write_bytes(payload)
        try:
            pages, _ = extraction.extract_pages_from_path(path, path.name, mime, False, "ukr+eng")
            assert pages and all("secret()" not in page.text for page in pages)
        except ValueError:
            pass
    assert time.monotonic() - started < 5.0


def test_fake_and_truncated_pdf_fuzz_fails_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(extraction, "_detected_mime", lambda path: "application/pdf")
    for index, payload in enumerate((b"%PDF-", b"%PDF-1.7\n%%EOF", b"%PDF-1.4\n1 0 obj\n<<>>")):
        path = tmp_path / f"bad-{index}.pdf"
        path.write_bytes(payload)
        with pytest.raises(ValueError):
            extraction.extract_pages_from_path(path, path.name, "application/pdf", False, "ukr+eng")
