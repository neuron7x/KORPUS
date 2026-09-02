"""Single source of truth for finite-sample Bernoulli uncertainty bounds.

The functions in this module are deliberately strict at the numeric boundary:
booleans, strings, NaN/Inf, negative counts and inconsistent Bernoulli counts are
rejected rather than coerced.  This keeps offline admission mathematics and TEVV
reporting on one executable contract.

ТРИ МЕЖІ, І ВИБІР МІЖ НИМИ НЕ СПРАВА СМАКУ.

`hoeffding_upper_bound` тримається для будь-якої обмеженої величини й тому не
користається з того, що показник помилки двійковий. `clopper_pearson_upper_bound` —
точна для біноміального; консервативна (покриття >= 1-delta), отже так само придатна
для ТВЕРДОЇ гарантії ризику. `wilson_score_interval` наближений: він недопокриває, і
для гарантії ризику не годиться взагалі — лише для звітності.

Ціна вибору виміряна 02.09.2026 при delta=0.05 і нулі спостережених помилок:

    довести ризик     Гефдінг       Клоппер-Пірсон
        10 %          150 зразків        29
         5 %          600                59
         2 %         3745               149
         1 %        14979               299

На 203 судимих питаннях, які є в дереві, Гефдінг засвідчує 8.65 %, точна межа — 1.49 %
на ТИХ САМИХ даних. Тобто ворота розгортання стояли на виборі методу, а не на якості
системи. Покриття обох перевіряється симуляцією в `test_exact_risk_bound.py`, і поруч
там стоїть негативний контроль — межа Вальда, яка ту саму перевірку зобов'язана
завалити.
"""

from __future__ import annotations

import math

from korpus.application.numeric_contracts import finite_number, strict_int

DEFAULT_TWO_SIDED_Z_95 = 1.959963984540054


def _bernoulli_counts(successes: object, total: object) -> tuple[int, int]:
    if not strict_int(successes):
        raise ValueError("successes must be an integer observation count")
    if not strict_int(total) or total < 0:
        raise ValueError("total must be a non-negative integer observation count")
    if successes < 0 or successes > total:
        raise ValueError("successes must lie within the number of observations")
    return successes, total


def _confidence_delta(delta: object) -> float:
    if not finite_number(delta):
        raise ValueError("delta must be finite and in (0, 1)")
    value = float(delta)
    if not 0.0 < value < 1.0:
        raise ValueError("delta must be finite and in (0, 1)")
    return value


def wilson_score_interval(
    successes: object,
    total: object,
    *,
    z: object = DEFAULT_TWO_SIDED_Z_95,
) -> tuple[float, float]:
    """Two-sided Wilson score interval for a Bernoulli proportion."""
    successes_i, total_i = _bernoulli_counts(successes, total)
    if not finite_number(z) or float(z) <= 0.0:
        raise ValueError("z must be finite and positive")
    if total_i == 0:
        return 0.0, 1.0

    zf = float(z)
    p = successes_i / total_i
    z2 = zf * zf
    denominator = 1.0 + z2 / total_i
    centre = (p + z2 / (2.0 * total_i)) / denominator
    spread = zf * math.sqrt(p * (1.0 - p) / total_i + z2 / (4.0 * total_i * total_i)) / denominator
    lower = max(0.0, centre - spread)
    upper = min(1.0, centre + spread)
    if abs(lower) < 1e-15:
        lower = 0.0
    return lower, upper


def hoeffding_upper_bound(
    errors: object,
    samples: object,
    delta: object,
    *,
    hypotheses: object = 1,
) -> float:
    """One-sided Hoeffding upper bound with Bonferroni/union-bound correction."""
    errors_i, samples_i = _bernoulli_counts(errors, samples)
    delta_f = _confidence_delta(delta)
    if not strict_int(hypotheses) or hypotheses < 1:
        raise ValueError("hypotheses must be a positive integer")
    if samples_i == 0:
        return 1.0

    local_delta = delta_f / hypotheses
    empirical = errors_i / samples_i
    radius = math.sqrt(math.log(1.0 / local_delta) / (2.0 * samples_i))
    return min(1.0, empirical + radius)


#: Кроків бісекції. 200 половинок доводять інтервал [0,1] нижче за подвійну точність,
#: тож результат детермінований: те саме входження дає той самий біт.
_BISECTION_STEPS = 200


def _binomial_tail_at_most(errors: int, total: int, rate: float) -> float:
    """P(X <= errors) для X ~ Binomial(total, rate)."""
    return math.fsum(
        math.comb(total, k) * rate**k * (1.0 - rate) ** (total - k) for k in range(errors + 1)
    )


def _union_corrected_delta(delta: object, hypotheses: object) -> float:
    """Поправка Бонферроні: одна впевненість, поділена між перевірками."""
    if not strict_int(hypotheses) or hypotheses < 1:
        raise ValueError("hypotheses must be a positive integer")
    return _confidence_delta(delta) / hypotheses


def clopper_pearson_upper_bound(
    errors: object,
    samples: object,
    delta: object,
    *,
    hypotheses: object = 1,
) -> float:
    """Точна одностороння біноміальна верхня межа. Порожній доказ дає 1.0.

    Чому вона стоїть поруч із Гефдінговою, а не замість неї, — у докстрінгу модуля.
    """
    errors_i, samples_i = _bernoulli_counts(errors, samples)
    local_delta = _union_corrected_delta(delta, hypotheses)
    if errors_i == samples_i:
        return 1.0
    low, high = errors_i / samples_i, 1.0
    for _ in range(_BISECTION_STEPS):
        middle = (low + high) / 2.0
        above = _binomial_tail_at_most(errors_i, samples_i, middle) > local_delta
        low, high = (middle, high) if above else (low, middle)
    return high


def hoeffding_two_sided_interval(
    successes: object,
    samples: object,
    delta: object,
) -> tuple[float, float]:
    """Distribution-free two-sided Hoeffding interval for bounded Bernoulli data."""
    successes_i, samples_i = _bernoulli_counts(successes, samples)
    delta_f = _confidence_delta(delta)
    if samples_i == 0:
        return 0.0, 1.0

    empirical = successes_i / samples_i
    radius = math.sqrt(math.log(2.0 / delta_f) / (2.0 * samples_i))
    return max(0.0, empirical - radius), min(1.0, empirical + radius)
