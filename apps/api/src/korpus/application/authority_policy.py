"""Normative authority-order invariant for calibrated retrieval priors."""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping

from korpus.domain.models import AuthorityClass

NORMATIVE_AUTHORITY_ORDER = (
    AuthorityClass.OFFICIAL_UA,
    AuthorityClass.OFFICIAL_ALLIED,
    AuthorityClass.MANUFACTURER,
    AuthorityClass.APPROVED_TRAINING,
    AuthorityClass.ANALYTICAL,
    AuthorityClass.HISTORICAL,
)


def _valid_prior(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0 <= float(value) <= 1
    )


def _strictly_descending(values: list[float]) -> bool:
    return all(left > right for left, right in itertools.pairwise(values))


def validate_authority_priors(priors: Mapping[AuthorityClass, float]) -> None:
    if set(priors) != set(AuthorityClass):
        raise ValueError("authority priors must cover every authority class exactly once")
    if not all(_valid_prior(value) for value in priors.values()):
        raise ValueError("authority priors must be finite values in [0, 1]")
    ordered = [float(priors[level]) for level in NORMATIVE_AUTHORITY_ORDER]
    if not _strictly_descending(ordered):
        raise ValueError("authority priors must strictly preserve normative authority order")
    floor = float(priors[AuthorityClass.HISTORICAL])
    if max(float(priors[AuthorityClass.ADVERSARY]), float(priors[AuthorityClass.UNKNOWN])) >= floor:
        raise ValueError("adversary and unknown priors must remain below historical authority")
