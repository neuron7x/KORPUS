"""Нічия на порозі допуску: рівність — не допуск.

`query_coverage` — частка малих цілих. Питання несе два-чотири змістовні токени, тож
досяжні значення це 0, 1/4, 1/3, 1/2, 2/3, 3/4 і 1. Поріг 0.5 лежить РІВНО на одному з
них, і «рівно на порозі» тут не крайовий випадок, а щільна подія.

Виміряно 07.09.2026 на живому розгортанні, на замороженому наборі
`evals/datasets/domain_boundary.jsonl`, усі 40 питань:

    чужі, що прорвались   out-07 out-08 out-09 out-19 — покриття рівно 0.50, усі чотири
    свої, що відповіли    19 із 19 — покриття 0.67, 0.75 або 1.00, жодного на 0.50

Клас нічиєї цілком складався з питань не про цей корпус.

ЧОМУ ЦЕЙ ТЕСТ ТУТ, А НЕ НАД HTTP. Перша спроба перевіряла правило через `/v1/answers`:
питання ставилось двічі, другого разу з порогом, піднятим до виміряного покриття
відповіді. Вона була зелена — і зелена ТАКОЖ із зумисне зіпсованим правилом (`>=`).
Причина: покриття ВІДПОВІДІ й покриття УРИВКА — різні числа, і при піднятому порозі
уривок відпадав раніше, на `retrieval_gate_failed`, так і не дійшовши до нічиєї. Тест
не торкався того, що обіцяв. Рівність виразна точно лише там, де її й перевіряють —
на самому предикаті.
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
THRESHOLDS = RiskThresholds(
    minimum_score=0.25,
    minimum_query_coverage=FLOOR,
    minimum_support_score=0.25,
    minimum_authority=0.46,
)


def _item(
    coverage: float, *, score: float = 0.9, authority: AuthorityClass = AuthorityClass.OFFICIAL_UA
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


def test_coverage_exactly_at_the_floor_is_refused() -> None:
    assert not coverage_admits(FLOOR, FLOOR)
    assert not evidence_is_eligible(_item(FLOOR), THRESHOLDS)


def test_coverage_above_the_floor_is_admitted() -> None:
    """Негативний контроль: правило відсікає нічию, а не все підряд."""
    assert coverage_admits(0.67, FLOOR)
    assert evidence_is_eligible(_item(0.67), THRESHOLDS)


def test_authority_exactly_at_the_floor_stays_admitted() -> None:
    """Вісь КЛАСУ, не виміру: нуль маржі тут означає навмисне включення.

    `minimum_authority` набуває значень 0.74, 0.46 і 0.0 — точно рівних пріоритетам
    `APPROVED_TRAINING`, `ANALYTICAL` та `UNKNOWN`. Майже весь корпус — `ANALYTICAL`,
    тож строгість на цій осі вимкнула б його цілком. Якщо колись строгість поширять
    «для симетрії» на всі осі, впаде саме цей тест.
    """
    item = _item(0.67, authority=AuthorityClass.ANALYTICAL)
    assert candidate_margins(item, THRESHOLDS).authority == 0.0
    assert evidence_is_eligible(item, THRESHOLDS)


def test_score_exactly_at_the_floor_stays_admitted() -> None:
    item = _item(0.67, score=THRESHOLDS.minimum_score)
    assert candidate_margins(item, THRESHOLDS).score == 0.0
    assert evidence_is_eligible(item, THRESHOLDS)


def test_the_reported_gate_is_the_applied_gate_at_the_tie() -> None:
    """Дві тотожності одного гейта мусять збігатись саме там, де вони можуть розійтись.

    `admission_boundary_summary` — те, чим PEC/DGC пояснюють рішення; `evidence_is_eligible`
    — те, що рантайм справді застосував. На нічиї `minimum_admission_margin` дорівнює
    нулю, і саме тут переказ правила замість самого правила дав би «пройшло».
    """
    at_the_tie = [_item(FLOOR)]
    summary = admission_boundary_summary(at_the_tie, THRESHOLDS)
    assert summary.minimum_admission_margin == 0.0
    assert summary.retrieval_gate_passed is evidence_is_eligible(at_the_tie[0], THRESHOLDS)
    assert summary.retrieval_gate_passed is False
