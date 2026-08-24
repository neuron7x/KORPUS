"""Whether an evaluation run is admissible as TEVV, and with what uncertainty.

`calibration_status` was the literal string `UNVALIDATED_TEST_FIXTURE` written into the
report. It said the right thing and it said it the same way regardless of what had been
run: a genuine measurement on a real corpus would have produced the same constant, and
nothing distinguished "we know this is a fixture" from "we never asked".

Two things are stated here.

**Provenance of the dataset.** A run is a fixture run unless the dataset declares a
real corpus — its identifier, who owns it, and the digest of the document set it was
drawn from. The declaration lives in the dataset, so a fixture cannot become a
measurement by changing a flag in the harness.

**Uncertainty.** A pass rate of 30/30 is not 1.0; it is "somewhere above 0.88 with 95%
confidence", and the difference matters when a number is used to decide whether a
system may be relied on. The Wilson interval is computed here rather than left to the
reader, and a run whose interval is wider than the policy allows is not admissible as
TEVV however good its point estimate looks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from korpus.application.tevv_math import validate_tevv_policy, wilson_bounds

FIXTURE_STATUS = "UNVALIDATED_TEST_FIXTURE"
MEASURED_STATUS = "MEASURED_ON_DECLARED_CORPUS"
REQUIRED_CORPUS_FIELDS = ("corpus_id", "owner", "document_set_sha256")


@dataclass(frozen=True)
class Interval:
    """A two-sided interval and the confidence it was computed at."""

    lower: float
    upper: float
    confidence: float

    @property
    def width(self) -> float:
        return self.upper - self.lower

    def as_dict(self) -> dict[str, float]:
        return {
            "lower": round(self.lower, 6),
            "upper": round(self.upper, 6),
            "width": round(self.width, 6),
            "confidence": self.confidence,
        }


def wilson_interval(successes: int, total: int, z: float = 1.959963985) -> Interval:
    """Wilson score interval — the normal approximation is wrong at the edges.

    At 30/30 the normal interval collapses to [1.0, 1.0], which reads as certainty from
    thirty observations. Wilson gives [0.885, 1.0]: the same data, honestly stated.
    """

    lower, upper = wilson_bounds(successes, total, z)
    return Interval(lower, upper, 0.95)


@dataclass(frozen=True)
class TevvVerdict:
    admissible: bool
    calibration_status: str
    interval: Interval
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "admissible_as_tevv": self.admissible,
            "calibration_status": self.calibration_status,
            "pass_rate_interval": self.interval.as_dict(),
            "reasons": list(self.reasons),
        }


def corpus_declaration_problems(declaration: Mapping[str, Any] | None) -> list[str]:
    """What is missing before a dataset may claim it describes a real corpus."""

    if not isinstance(declaration, Mapping):
        return ["dataset declares no corpus: the run is a fixture run"]
    problems = [
        f"corpus declaration is missing {field}"
        for field in REQUIRED_CORPUS_FIELDS
        if not declaration.get(field)
    ]
    digest = declaration.get("document_set_sha256")
    if isinstance(digest, str) and digest and len(digest) != 64:
        problems.append("corpus document_set_sha256 is malformed")
    if declaration.get("synthetic") is True:
        problems.append("corpus declares itself synthetic")
    return problems


def evaluate_tevv(
    *,
    passed: int,
    total: int,
    corpus_declaration: Mapping[str, Any] | None,
    maximum_interval_width: float,
    minimum_observations: int,
) -> TevvVerdict:
    """Decide whether this run may be cited as a measurement of the system."""

    maximum_interval_width, minimum_observations = validate_tevv_policy(
        maximum_interval_width, minimum_observations
    )

    reasons = corpus_declaration_problems(corpus_declaration)
    interval = wilson_interval(passed, total)
    if total < minimum_observations:
        reasons.append(
            f"{total} observations is below the floor of {minimum_observations}: "
            "a point estimate from too few queries is not a measurement"
        )
    if interval.width > maximum_interval_width:
        reasons.append(
            f"95% interval is {interval.width:.3f} wide, above the maximum "
            f"{maximum_interval_width:.3f}: the run does not constrain the answer enough"
        )
    admissible = not reasons
    return TevvVerdict(
        admissible=admissible,
        calibration_status=MEASURED_STATUS if admissible else FIXTURE_STATUS,
        interval=interval,
        reasons=tuple(reasons),
    )
