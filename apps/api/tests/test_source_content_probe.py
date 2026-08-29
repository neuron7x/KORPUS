"""The probe's measurement must survive its own previous success.

probe_source_content.py repoints source_uri to the variant it measured as richest. That
makes the second run read back a URI the first run already changed. If the variant table is
built from the stored URI without normalising it, run two compares /print against
/print/print, labels the first "card", and reports a card richer than its print variant —
the measurement inverted by having worked. These pin the normalisation and the shape of
what it records, without touching the network.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ACT = "https://zakon.rada.gov.ua/laws/show/548-14"


def _probe_module():
    spec = importlib.util.spec_from_file_location(
        "probe_source_content", ROOT / "scripts/probe_source_content.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_variants_of_a_card_uri() -> None:
    assert _probe_module()._variants(ACT) == {"card": ACT, "print": ACT + "/print"}


def test_variants_of_an_already_repointed_uri_are_the_same_pair() -> None:
    """The idempotence the second run depends on."""
    module = _probe_module()
    assert module._variants(ACT + "/print") == module._variants(ACT)


def test_a_trailing_slash_does_not_create_a_third_variant() -> None:
    module = _probe_module()
    assert module._variants(ACT + "/print/") == module._variants(ACT)


def test_measure_counts_words_tables_and_attachments() -> None:
    html = (
        "<html><body><p>один два три</p><table><tr><td>x</td></tr></table>"
        '<a href="/laws/file/text/135/f1.docx">анекс</a></body></html>'
    )
    measured = _probe_module()._measure(html, ACT)
    assert measured["uri"] == ACT
    assert measured["words"] == 5  # три слова + комірка таблиці + текст посилання
    assert measured["tables"] == 1
    assert measured["attachments"] == ["https://zakon.rada.gov.ua/laws/file/text/135/f1.docx"]


def test_an_absolute_attachment_link_is_left_alone() -> None:
    html = '<a href="https://example.org/a.pdf">x</a>'
    assert _probe_module()._measure(html, ACT)["attachments"] == ["https://example.org/a.pdf"]


def test_a_source_on_an_unprobed_host_is_skipped() -> None:
    entry = {"id": "X", "source_uri": "https://mod.gov.ua/pro-nas/suhoputni-vijska"}
    assert _probe_module().probe(entry, timeout=1) is None
