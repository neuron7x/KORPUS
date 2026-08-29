from __future__ import annotations

import math
from typing import Any

ABSTAINED = {"insufficient_evidence", "requires_human_review"}


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    if total <= 0:
        return [0.0, 0.0]
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


def retrieval_effectiveness(results: list[dict[str, Any]]) -> dict[str, Any]:
    retrieval = [result for result in results if result["kind"] == "retrieval"]
    answered = [result for result in retrieval if result["status"] == "answered"]
    supported = [result for result in answered if result["passed"]]
    abstained = [result for result in retrieval if result["status"] in ABSTAINED]
    total = len(retrieval)
    return {
        "cases": total,
        "answered": len(answered),
        "abstained": len(abstained),
        "answered_wrong_or_invalid_source": len(answered) - len(supported),
        "supported_answers": len(supported),
        "answer_yield": len(answered) / total if total else 0.0,
        "supported_answer_rate": len(supported) / total if total else 0.0,
        "supported_answer_rate_wilson_95": wilson_interval(len(supported), total),
        "interpretation": (
            "Safety PASS permits abstention. supported_answer_rate measures how often "
            "the system both answered and cited a frozen version that holds the target evidence."
        ),
    }
