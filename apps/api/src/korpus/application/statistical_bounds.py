"""Single source of truth for finite-sample Bernoulli uncertainty bounds.

The functions in this module are deliberately strict at the numeric boundary:
booleans, strings, NaN/Inf, negative counts and inconsistent Bernoulli counts are
rejected rather than coerced.  This keeps offline admission mathematics and TEVV
reporting on one executable contract.
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
