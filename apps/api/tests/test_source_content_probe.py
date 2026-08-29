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

import pytest

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


def test_one_thin_response_cannot_lower_a_variant_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """The portal is not deterministic, so a single sample is not a measurement.

    On 2026-08-29 the card for z0927-20 returned 736 words in one run and 5583 in another,
    minutes apart, both HTTP 200. With one sample per variant, the thin reading repointed
    three sources onto the weaker variant and rewrote the recorded numbers to match — the
    probe undoing its own earlier, better reading. Scoring by the largest of several
    readings means a short response can only fail to raise a score, never lower one.
    """
    module = _probe_module()
    full = "<html>" + " ".join(["слово"] * 500) + "<table></table></html>"
    thin = "<html>сторінка недоступна</html>"
    responses = {ACT: [thin, full, thin], ACT + "/print": [thin, thin, thin]}

    def fake_fetch(uri: str, timeout: int) -> str:
        queue = responses[uri]
        return queue.pop(0) if queue else thin

    monkeypatch.setattr(module, "_fetch", fake_fetch)
    result = module.probe({"id": "X", "source_uri": ACT}, timeout=1, sample_count=3)
    assert result is not None
    assert result["chosen_variant"] == "card", result["word_readings"]
    assert result["chosen_words"] == 500  # the full reading, not the thin one
    assert result["word_readings"]["card"] == [2, 2, 500]
    assert result["samples_per_variant"] == 3


def test_a_single_sample_reproduces_the_defect_this_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative control: with one sample the thin reading wins and the score collapses."""
    module = _probe_module()
    thin = "<html>сторінка недоступна</html>"
    monkeypatch.setattr(module, "_fetch", lambda uri, timeout: thin)
    result = module.probe({"id": "X", "source_uri": ACT}, timeout=1, sample_count=1)
    assert result is not None
    assert result["chosen_words"] == 2
