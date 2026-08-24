from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from korpus.application.load_math import _count_5xx, evaluate_load_numbers

STEADY_P95_LIMIT_SECONDS = 5.0
COLD_START_LIMIT_SECONDS = 5.0
SUBJECT_THROTTLE_REASON = "subject_share_exhausted"


def evaluate_load_slos(report: Mapping[str, Any]) -> dict[str, bool]:
    """Evaluate measured load quality; provenance and attestation remain separate gates."""
    return evaluate_load_numbers(
        report, STEADY_P95_LIMIT_SECONDS, COLD_START_LIMIT_SECONDS, SUBJECT_THROTTLE_REASON
    )
