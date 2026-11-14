"""Release mutation aggregation preserves every invalid or unknown observation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def campaign_summary(results: Sequence[Mapping[str, object]]) -> dict[str, object]:
    killed = sum(row.get("status") == "KILLED" for row in results)
    survived = [str(row.get("id")) for row in results if row.get("status") == "SURVIVED"]
    invalid = [
        str(row.get("id")) for row in results if row.get("status") not in ("KILLED", "SURVIVED")
    ]
    return {
        "mutants": len(results),
        "killed": killed,
        "survived": survived,
        "invalid": invalid,
        "status": "PASS" if results and killed == len(results) else "FAIL",
    }
