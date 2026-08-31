"""Посилання, перевірене за формою, пропускає будь-яку підміну адресата.

`citation_traceability` рахує частку версій, чий `source_uri` не є голим доменом — і сам
це декларує в `cannot_judge`. Виміряно 31.08.2026 адверсарним прогоном: усі 97 похідних
статей перевели на завідомо хибний статут (вартові й днювальні — у дисциплінарний), і вісь
лишилась байт у байт `0.95703125`, код виходу 0.

Тому підтвердження робиться ТЕКСТОМ названого джерела: початок похідної статті мусить бути
підрядком оригіналу з object-store. Та сама отрута на цій перевірці дає 2 із 97 і код 1.

Читається оригінал, а не зшиті прольоти: зшивання встик вставляє перекриття, обрізане
посеред слова — виміряно 325 сфабрикованих стиків із 533 у статуті 548-14.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from relink_derived_articles import disambiguate, resolve  # noqa: E402
from validate_derived_source_links import confirm  # noqa: E402

GUARD = (
    "Вивідний зобов'язаний охороняти пост, не залишати його без наказу начальника варти "
    "та доповідати про кожне порушення негайно."
)
DISCIPLINE = (
    "Командир накладає стягнення на порушника з урахуванням ступеня вини, попередньої "
    "поведінки та розміру завданих державі збитків."
)
STATUTES = {
    "guard": (
        "https://zakon.rada.gov.ua/laws/show/550-14/print",
        "Стаття 244. " + GUARD + " Далі інший текст.",
    ),
    "discipline": ("https://zakon.rada.gov.ua/laws/show/551-14/print", "Стаття 104. " + DISCIPLINE),
}


def test_a_head_the_named_source_carries_is_confirmed() -> None:
    assert confirm(GUARD + "а" * 60, STATUTES["guard"][1]) == 120


def test_a_head_the_named_source_does_not_carry_is_refused() -> None:
    """Це і є та перевірка, якої бракувало: підміна адресата стає видимою."""
    assert confirm(DISCIPLINE * 3, STATUTES["guard"][1]) is None


def test_text_that_runs_into_the_next_role_is_confirmed_by_a_shorter_prefix() -> None:
    """«Начальник варти з охорони штабів… (ст.219)» на 100-му символі вже про іншу роль.

    Фіксовані 120 символів губили справжню прив'язку; проба спадає, і саме тому стаття
    знайшлась. Коротший префікс тут не послаблення — він звіряється з ОРИГІНАЛОМ.
    """
    runs_on = GUARD[:100] + " Помічник начальника варти підпорядковується начальникові варти."

    assert confirm(runs_on, STATUTES["guard"][1]) == 100


def test_whitespace_does_not_decide_whether_a_quote_belongs_to_its_source() -> None:
    assert confirm(GUARD.replace(" ", "\n  ", 3) + "а" * 60, STATUTES["guard"][1]) == 120


def test_a_single_parent_is_linked_and_the_probe_length_is_recorded() -> None:
    links, skipped = resolve([("d", "Обов'язки: Вивідний", GUARD)], STATUTES)

    assert [link["parent"] for link in links] == ["guard"]
    assert links[0]["probe_chars"] == 120
    assert skipped == {"no_probe": 0, "not_found": 0, "ambiguous": 0}


def test_a_head_two_statutes_both_carry_is_left_alone_rather_than_guessed() -> None:
    """Двозначність справжня: «Начальник служби пожежної безпеки (ст.195)» дослівно є
    і в 548-14, і в 550-14. Здогад тут коштує хибного посилання під хешем."""
    both = {name: (url, GUARD) for name, (url, _text) in STATUTES.items()}
    links, skipped = resolve([("d", "Обов'язки: Хтось", GUARD)], both)

    assert links == []
    assert skipped["ambiguous"] == 1


def test_a_head_no_statute_carries_is_left_alone() -> None:
    links, skipped = resolve(
        [("d", "Обов'язки: Хтось", "Текст, якого немає в жодному статуті, і він досить довгий.")],
        STATUTES,
    )

    assert links == []
    assert skipped["not_found"] == 1


# ── Двозначність, яку входження розв'язати не може, бо воно вже сказало все, що могло.
# «Начальник служби пожежної безпеки… (ст.195)» дослівно є І в 548-14, І в 550-14. Але в
# першому текст стоїть під статтею 195, у другому — під 21, і номер у назві збігається
# рівно з одним. Це вимір ІНШОЇ властивості, а не глибше вдивляння в ту саму.

BOTH = {
    "внутрішньої": "195. Начальник служби пожежної безпеки. " + GUARD,
    "гарнізонної": "21. Інша стаття зовсім. " + GUARD,
}


def test_the_article_number_settles_what_containment_cannot() -> None:
    settled = disambiguate("Обов'язки: Хтось (Статут, ст.195)", list(BOTH), BOTH, GUARD[:60])

    assert settled == "внутрішньої"


def test_a_number_matching_two_candidates_is_left_unsettled() -> None:
    """Розв'язувач, який вгадує при нічиї, гірший за той, що відмовляється."""
    tie = {name: "195. Заголовок. " + GUARD for name in BOTH}

    assert disambiguate("Обов'язки: Хтось (Статут, ст.195)", list(tie), tie, GUARD[:60]) is None


def test_a_number_matching_nobody_is_left_unsettled() -> None:
    assert disambiguate("Обов'язки: Хтось (Статут, ст.777)", list(BOTH), BOTH, GUARD[:60]) is None


def test_a_small_number_is_not_trusted_because_it_is_usually_a_part_index() -> None:
    """Виміряно на 97 прив'язках: «ст.N» — номер статті у 86, номер ЧАСТИНИ в 11.

    Усі одинадцять мають N ≤ 3 або форму «11-1» — «(Статут, ст.1)» лежало під
    «{Стаття 112 із змінами} - 1 .». На таких номерах розв'язувач мовчить, а не вгадує.
    """
    small = {"a": "2. Заголовок. " + GUARD, "b": "9. Інший. " + GUARD}

    assert disambiguate("Обов'язки: Хтось (Статут, ст.2)", list(small), small, GUARD[:60]) is None
