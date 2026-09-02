"""Точна біноміальна межа ризику: чи вона справді покриває те, що обіцяє.

Межу легко написати й неможливо перевірити читанням: помилка в один крок бісекції або
переплутаний бік нерівності дає число, яке виглядає правдоподібно й тихо занижує ризик.
Тому тут не звіряються формули — тут МІРЯЄТЬСЯ покриття на симуляції з фіксованим зерном,
і поруч стоїть негативний контроль: наближена межа Вальда мусить ЗАВАЛИТИ ту саму
перевірку. Без нього тест не доводить нічого — він був би зелений і для константи.
"""

from __future__ import annotations

import math
import random

import pytest
from korpus.application.statistical_bounds import (
    clopper_pearson_upper_bound,
    hoeffding_upper_bound,
)

DELTA = 0.05
TRIALS = 4000
SEED = 20260902


def _wald_upper(errors: int, samples: int) -> float:
    """Наближена межа з підручника. Стоїть тут РІВНО щоб провалитись."""
    rate = errors / samples
    return min(1.0, rate + 1.6448536269514722 * math.sqrt(rate * (1.0 - rate) / samples))


def _coverage(bound, samples: int, true_rate: float) -> float:
    rng = random.Random(SEED)
    covered = sum(
        1
        for _ in range(TRIALS)
        if bound(sum(1 for _ in range(samples) if rng.random() < true_rate), samples) >= true_rate
    )
    return covered / TRIALS


@pytest.mark.parametrize("true_rate", [0.02, 0.05, 0.20])
def test_the_exact_bound_covers_the_true_rate_at_least_as_often_as_promised(true_rate):
    coverage = _coverage(lambda e, n: clopper_pearson_upper_bound(e, n, DELTA), 40, true_rate)
    assert coverage >= 1.0 - DELTA, f"покриття {coverage} нижче за обіцяне {1 - DELTA}"


def test_the_textbook_approximation_fails_the_same_check():
    """Негативний контроль. Якщо ЦЕ раптом пройде — перевірка покриття мертва."""
    coverage = _coverage(_wald_upper, 40, 0.05)
    assert coverage < 1.0 - DELTA, (
        f"межа Вальда дала покриття {coverage}: перевірка покриття перестала розрізняти"
    )


def test_zero_errors_matches_the_closed_form():
    """При нулі помилок точна межа має замкнену форму 1 - delta**(1/n)."""
    for samples in (1, 7, 59, 203, 1000):
        expected = 1.0 - DELTA ** (1.0 / samples)
        assert clopper_pearson_upper_bound(0, samples, DELTA) == pytest.approx(expected, abs=1e-12)


def test_the_bound_moves_in_the_only_two_directions_it_may():
    base = clopper_pearson_upper_bound(2, 200, DELTA)
    assert clopper_pearson_upper_bound(3, 200, DELTA) > base, "більше помилок — не вужча межа"
    assert clopper_pearson_upper_bound(2, 400, DELTA) < base, "більше зразків — не ширша межа"
    assert clopper_pearson_upper_bound(2, 200, DELTA, hypotheses=4) > base, "поправка не діє"


def test_it_is_not_looser_than_hoeffding_on_the_grid_that_decides_deployment():
    """Виміряне твердження, не загальне: на цій сітці точна межа не гірша.

    Саме ця сітка вирішує ворота розгортання (`minimum_calibration_samples` 200 і вище),
    і саме на ній різниця у 5.8x перетворює «недосяжно» на «доведено».
    """
    for samples, errors in [(30, 0), (203, 0), (200, 2), (600, 6), (1000, 10)]:
        exact = clopper_pearson_upper_bound(errors, samples, DELTA)
        loose = hoeffding_upper_bound(errors, samples, DELTA)
        assert exact <= loose, f"n={samples} e={errors}: {exact} > {loose}"


def test_impossible_and_empty_evidence_fail_closed():
    assert clopper_pearson_upper_bound(0, 0, DELTA) == 1.0
    assert clopper_pearson_upper_bound(5, 5, DELTA) == 1.0


@pytest.mark.parametrize(
    ("errors", "samples", "delta"),
    [(True, 10, 0.05), (-1, 10, 0.05), (11, 10, 0.05), (1, 10, 0.0), (1, 10, float("nan"))],
)
def test_the_numeric_boundary_is_refused_not_coerced(errors, samples, delta):
    with pytest.raises(ValueError):
        clopper_pearson_upper_bound(errors, samples, delta)


def test_a_hypothesis_count_that_is_not_a_positive_integer_is_refused():
    with pytest.raises(ValueError):
        clopper_pearson_upper_bound(1, 10, DELTA, hypotheses=0)


def test_the_deployment_gate_reads_the_exact_bound_and_not_the_loose_one():
    """Розрізняльний випадок, а не переказ реалізації.

    203 судимих питання — рівно стільки їх у дереві — при нулі помилок і межі ризику 2 %:
    точна межа дає 0.0146 і ворота ВІДЧИНЯЮТЬСЯ, Гефдінгова дає 0.0859 і вони зачинені.
    Профіль, що мовчки повернеться до вільнішої межі, завалить саме цей тест; решта
    перевірок каліброваності відношенн і не помітять підміни.
    """
    from korpus.application.calibration import CalibrationProfile

    profile = CalibrationProfile(
        profile_id="exact-bound-discriminating-case",
        dataset_sha256="a" * 64,
        accepted_samples=203,
        observed_errors=0,
        confidence_delta=DELTA,
        risk_limit=0.02,
        minimum_score=0.4,
        minimum_query_coverage=0.5,
        minimum_support_score=0.35,
        minimum_calibration_samples=200,
        ranking_evaluated_queries=500,
        ndcg_at_10=0.82,
        mrr_at_10=0.86,
        recall_at_20=0.94,
    )
    assert profile.upper_error_bound == pytest.approx(0.014649, abs=1e-5)
    assert hoeffding_upper_bound(0, 203, DELTA) > profile.risk_limit
    assert profile.selective_answering_valid is True
