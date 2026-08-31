"""«Показати, ДЕ САМЕ це написано» — половина ціннісної функції, і вона не мірялась.

Виміряно 31.08.2026 прямо по базі, яка обслуговується: 148 із 256 версій (57.8 %) мають
посилання на КОНКРЕТНИЙ документ, а 107 указують на `https://zakon.rada.gov.ua/` —
титульну сторінку порталу. Читач бачить кнопку «Відкрити точний фрагмент», офіційну
назву статуту, хеш — і посилання на головну.

Обидві осі — про КОРПУС, не про конвеєр, тож жоден прогін питань їх не бачив. Саме тому
невиміряна вісь і виявилась найслабшою, щойно її поміряли: 0.1555 проти 0.75 у
найслабшої з поміж тих, що вже мірялись.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_corpus_integrity import sentence_starts, traceability  # noqa: E402


def test_a_link_to_a_document_counts_and_a_link_to_the_portal_does_not() -> None:
    result = traceability(["https://zakon.rada.gov.ua/laws/show/123", "https://zakon.rada.gov.ua/"])

    assert result["deep"] == 1
    assert result["bare"] == 1
    assert result["rate"] == 0.5


def test_a_bare_domain_with_or_without_a_slash_is_the_same_thing() -> None:
    """Негативний контроль на саму регулярку: скісна не робить посилання глибоким."""
    assert traceability(["https://a.gov", "https://a.gov/"])["deep"] == 0


def test_a_missing_link_is_not_credited_as_deep() -> None:
    """Відсутнє посилання гірше за поверхневе, і вже точно не краще."""
    assert traceability([None, ""])["deep"] == 0


def test_an_empty_corpus_has_no_rate_rather_than_a_perfect_one() -> None:
    """Частка над порожнім — відсутність виміру, а не одиниця."""
    assert traceability([])["rate"] is None
    assert sentence_starts([])["rate"] is None


def test_a_passage_that_starts_mid_sentence_is_counted_as_such() -> None:
    result = sentence_starts(["Речення ціле.", "ня рани Зупинка кровотечі"])

    assert result["mid_sentence"] == 1
    assert result["rate"] == 0.5
