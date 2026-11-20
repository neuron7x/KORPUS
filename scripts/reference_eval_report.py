"""Per-stratum reference reports with FAIL > UNKNOWN > PASS precedence."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from reference_eval_metrics import retrieval_effectiveness


def _buckets(results: list[dict[str, Any]], key: str) -> dict[str, dict[str, int]]:
    buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {"cases": 0, "passed": 0, "unavailable": 0}
    )
    for result in results:
        bucket = buckets[result[key]]
        if result.get("unavailable"):
            bucket["unavailable"] += 1
        else:
            bucket["cases"] += 1
            bucket["passed"] += int(result["passed"] is True)
    return dict(sorted(buckets.items()))


def reference_report(
    results: list[dict[str, Any]], meta: dict[str, Any], base: str, default_as_of: str
) -> dict[str, Any]:
    unavailable = [result for result in results if result.get("unavailable")]
    judged = [result for result in results if not result.get("unavailable")]
    failures = [result for result in judged if result["passed"] is not True]
    status = "FAIL" if failures else ("UNKNOWN" if unavailable or not results else "PASS")
    return {
        "schema_version": 1,
        "ran_at": datetime.now(UTC).isoformat(),
        "base": base,
        "default_as_of": default_as_of,
        "reference_set_digest": meta["content_digest"],
        "reference_set_frozen_at": meta["frozen_at"],
        "cases": len(results),
        "judged": len(judged),
        "unavailable": len(unavailable),
        "unavailable_statuses": dict(
            sorted(Counter(str(result["status"]) for result in unavailable).items())
        ),
        "passed": sum(result["passed"] is True for result in judged),
        "by_kind": _buckets(results, "kind"),
        "retrieval_effectiveness": retrieval_effectiveness(judged),
        "by_stratum": _buckets(results, "stratum"),
        "failures": failures[:40],
        "unavailable_cases": [result["id"] for result in unavailable],
        "status": status,
        "cannot_judge": meta["cannot_judge"],
    }
