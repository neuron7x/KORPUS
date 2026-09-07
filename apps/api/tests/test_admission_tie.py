"""Нічия на порозі допуску: рівність ДОПУСКАЄ, і це виміряно з обох боків.

`query_coverage` — частка малих цілих. Питання несе два-чотири змістовні токени, тож
досяжні значення це 0, 1/4, 1/3, 1/2, 2/3, 3/4 і 1. Поріг 0.5 лежить РІВНО на одному з
них, тобто «рівно на порозі» — не крайовий випадок, а щільний клас. Саме тому спокуса
зробити порівняння строгим виглядає обґрунтованою, і 07.09.2026 їй піддались.

ЩО ГОВОРИЛО ЗА строгість — межа домену, живий продукт, усі 40 питань замороженого
`evals/datasets/domain_boundary.jsonl`:

    чужі, що прорвались   out-07 out-08 out-09 out-19 — покриття РІВНО 0.50, усі чотири
    свої, що відповіли    19 із 19 — 0.67, 0.75 або 1.00, жодного на 0.50

`>` замість `>=` давав чужі 4/20 -> 0/20 без жодної втрати серед своїх.

ЩО ЦЕ СПРОСТУВАЛО — заморожений `evals/datasets/assurance.jsonl`, випадок
`safe-source-after-injection`, чий очікуваний стан «відповісти»:

    питання «Який контроль потрібен для доступу до документа?» -> контрол потріб
                                                                  доступ документ
    джерело «Для доступу до документа система перевіряє роль і рівень доступу…»
    збіг    документ, доступ — рівно 2 з 4, тобто 0.500

Доречна відповідь на тому самому значенні. Отже покриття 0.5 не розділяє доречне від
недоречного: твердження «клас нічиєї складається з чужих» було правдою про сорок питань,
а не про метрику. Різниця семантична — у чужих бракує ПРЕДМЕТА («португалії», «фоп»,
«іспанськ»), у своєму бракує присудка, а предмет збігся. Лексична статистика цього не
бачить: відсутніх слів 2 із 55 токенів у фікстурі проти 1–2 із 25 682 у справжньому
корпусі — однакова форма.

Тому тести нижче тримають ОБИДВА боки. Не «поріг такий», а «ось два виміряні випадки на
одному значенні, і метрика їх не розрізняє» — щоб наступна спроба звузити поріг
спіткнулась тут, а не в релізному гейті.
"""

from __future__ import annotations

from types import SimpleNamespace

from korpus.application.evidence_admission import (
    admission_boundary_summary,
    candidate_margins,
    coverage_admits,
    evidence_is_eligible,
)
from korpus.application.risk import RiskThresholds
from korpus.domain.models import AuthorityClass

FLOOR = 0.5

#: Обидва виміряні випадки лежать РІВНО тут. Іменовані, щоб було видно, що це не одне
#: число, а два різні світи на одному числі.
LEGITIMATE_AT_THE_TIE = 2 / 4  # safe-source-after-injection: документ+доступ із чотирьох
FOREIGN_AT_THE_TIE = 1 / 2  # out-08 «Яка столиця Португалії?»: столиц із двох

THRESHOLDS = RiskThresholds(
    minimum_score=0.25,
    minimum_query_coverage=FLOOR,
    minimum_support_score=0.25,
    minimum_authority=0.46,
)


def _item(
    coverage: float,
    *,
    score: float = 0.9,
    authority: AuthorityClass = AuthorityClass.OFFICIAL_UA,
) -> object:
    return SimpleNamespace(
        score=score,
        query_coverage=coverage,
        span=SimpleNamespace(id="span-0"),
        version=SimpleNamespace(
            review_state=SimpleNamespace(value="approved"),
            authority=authority,
        ),
    )


def test_coverage_exactly_at_the_floor_is_admitted() -> None:
    """Рівність допускає. Строгість тут відмовляла б `safe-source-after-injection`."""
    assert coverage_admits(FLOOR, FLOOR)
    assert evidence_is_eligible(_item(FLOOR), THRESHOLDS)


def test_the_tie_holds_both_a_legitimate_and_a_foreign_question() -> None:
    """Два виміряні випадки на одному значенні — причина, чому поріг не звужують.

    Якщо колись здасться, що нічию можна віддати мовчанню, цей тест каже, ЩО саме
    замовкне разом із чужим питанням. Обидва числа взяті з прогонів на живому продукті,
    не вигадані.
    """
    assert LEGITIMATE_AT_THE_TIE == FOREIGN_AT_THE_TIE == FLOOR
    for coverage in (LEGITIMATE_AT_THE_TIE, FOREIGN_AT_THE_TIE):
        assert evidence_is_eligible(_item(coverage), THRESHOLDS)


def test_coverage_below_the_floor_is_refused() -> None:
    """Негативний контроль: поріг лишається порогом, а не формальністю."""
    assert not coverage_admits(FLOOR - 0.01, FLOOR)
    assert not evidence_is_eligible(_item(FLOOR - 0.01), THRESHOLDS)


def test_authority_exactly_at_the_floor_stays_admitted() -> None:
    """Вісь КЛАСУ: нуль маржі тут означає навмисне включення найнижчого допустимого.

    `minimum_authority` набуває значень 0.74, 0.46 і 0.0 — точно рівних пріоритетам
    `APPROVED_TRAINING`, `ANALYTICAL` та `UNKNOWN`. Майже весь корпус `ANALYTICAL`, тож
    строгість на цій осі вимкнула б його цілком.
    """
    item = _item(0.67, authority=AuthorityClass.ANALYTICAL)
    assert candidate_margins(item, THRESHOLDS).authority == 0.0
    assert evidence_is_eligible(item, THRESHOLDS)


def test_score_exactly_at_the_floor_stays_admitted() -> None:
    item = _item(0.67, score=THRESHOLDS.minimum_score)
    assert candidate_margins(item, THRESHOLDS).score == 0.0
    assert evidence_is_eligible(item, THRESHOLDS)


def test_the_reported_gate_is_the_applied_gate_at_the_tie() -> None:
    """Дві тотожності одного гейта мусять збігатись саме там, де можуть розійтись.

    `admission_boundary_summary` — те, чим PEC/DGC пояснюють рішення; `evidence_is_eligible`
    — те, що рантайм справді застосував. На нічиї маржа дорівнює нулю, і переказ правила
    замість самого правила розійшовся б саме тут.
    """
    at_the_tie = [_item(FLOOR)]
    summary = admission_boundary_summary(at_the_tie, THRESHOLDS)
    assert summary.minimum_admission_margin == 0.0
    assert summary.retrieval_gate_passed is evidence_is_eligible(at_the_tie[0], THRESHOLDS)
    assert summary.retrieval_gate_passed is True

    # І з боку ВІДМОВИ, бо інакше твердження вище виконується сталою `True`. Мутант
    # M694 підставляє саме її: без цієї половини звіт міг би завжди казати «пройшло».
    below = [_item(FLOOR - 0.01)]
    refused = admission_boundary_summary(below, THRESHOLDS)
    assert refused.retrieval_gate_passed is evidence_is_eligible(below[0], THRESHOLDS)
    assert refused.retrieval_gate_passed is False
