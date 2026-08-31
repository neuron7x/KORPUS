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

from measure_corpus_integrity import span_quality, traceability  # noqa: E402


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
    assert span_quality([], {})["rate"] is None


#: Джерело, проти якого судяться прольоти. Вимір читає ОРИГІНАЛ, а не сусідні прольоти,
#: бо зшивання прольотів встик вставляє перекриття, обрізане посеред слова.
SOURCE = {"v": "Перше речення тут. Друге речення тут. Третє речення тут."}


def test_a_passage_that_starts_mid_sentence_is_counted_as_such() -> None:
    """Вимір точний: дивиться символ ПЕРЕД прольотом у джерелі, не велику літеру в ньому.

    Орфографічний сурогат, який тут стояв, завищував на 0.077 і піднімався на 0.20 від
    зміни однієї константи `MAX_SPAN_CHARS`, не додавши жодного символу інформації.
    """
    result = span_quality([("v", "Друге речення тут."), ("v", "речення тут. Третє")], SOURCE)

    assert result["sentence_start"] == 1
    assert result["rate"] == 0.5


def test_a_passage_that_is_not_a_verbatim_slice_of_its_source_is_not_credited() -> None:
    """Найдорожчий урок 31.08.2026: ремонт меж зробив 61 % прольотів недослівними.

    Він склеїв 9389 швів у слова, яких у документі немає — `stabilityttacks`,
    `andontact`, `Servicexperiencing`. Власний інваріант ремонту («конкатенація прольотів
    версії незмінна») зберігається при перенесенні символів між сусідами ЗАВЖДИ, тож
    побачити цього не міг. Ось перевірка, яка може.
    """
    glued = span_quality([("v", "Перше речення тут.Друге")], SOURCE)

    assert glued["verbatim"] == 0
    assert glued["verbatim_rate"] == 0.0


def test_a_verbatim_slice_is_credited_so_the_axis_is_not_merely_a_refusal() -> None:
    """Негативний контроль: вісь, яка не зараховує нічого, нічого й не міряє."""
    assert span_quality([("v", "Друге речення тут.")], SOURCE)["verbatim_rate"] == 1.0


def test_a_passage_whose_source_is_absent_is_counted_apart_not_credited() -> None:
    """«Не знайшли» — це не «в порядку»: такий проліт не кредитується жодною з осей.

    Два різні способи не знайтись, і обидва мусять поводитись однаково: джерела немає
    взагалі, і джерело є, але тексту в ньому немає. Перший випадок сам по собі мутанта не
    ловив — гілка, яка кредитувала б знахідку, лежить у другому.
    """
    no_source = span_quality([("немає", "будь-що")], SOURCE)

    assert no_source["unlocatable"] == 1
    assert no_source["verbatim"] == 0
    assert no_source["sentence_start"] == 0

    not_in_source = span_quality([("v", "Цього рядка в джерелі немає зовсім.")], SOURCE)

    assert not_in_source["unlocatable"] == 1
    assert not_in_source["verbatim"] == 0
    assert not_in_source["sentence_start"] == 0
    assert not_in_source["rate"] == 0.0
