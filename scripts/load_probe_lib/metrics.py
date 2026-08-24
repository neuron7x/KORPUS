from __future__ import annotations

import json
import statistics
import urllib.error
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Outcome:
    latencies: list[float] = field(default_factory=list)
    statuses: dict[str, int] = field(default_factory=dict)
    decisions: dict[str, int] = field(default_factory=dict)
    refusal_reasons: dict[str, int] = field(default_factory=dict)

    def record(
        self, seconds: float, status: str, decision: str = "", refusal_reason: str = ""
    ) -> None:
        self.latencies.append(seconds)
        self.statuses[status] = self.statuses.get(status, 0) + 1
        if decision:
            self.decisions[decision] = self.decisions.get(decision, 0) + 1
        if refusal_reason:
            self.refusal_reasons[refusal_reason] = self.refusal_reasons.get(refusal_reason, 0) + 1

    def summary(self) -> dict[str, Any]:
        ordered = sorted(self.latencies)
        if not ordered:
            return {"requests": 0}

        def at(fraction: float) -> float:
            index = min(len(ordered) - 1, int(fraction * len(ordered)))
            return round(ordered[index], 3)

        return {
            "requests": len(ordered),
            "p50_seconds": at(0.50),
            "p95_seconds": at(0.95),
            "p99_seconds": at(0.99),
            "max_seconds": round(ordered[-1], 3),
            "mean_seconds": round(statistics.fmean(ordered), 3),
            "statuses": dict(sorted(self.statuses.items())),
            "decisions": dict(sorted(self.decisions.items(), key=lambda item: -item[1])),
            "refusal_reasons": dict(
                sorted(self.refusal_reasons.items(), key=lambda item: (-item[1], item[0]))
            ),
        }


def refusal_reason(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read() or b"{}")
    except (ValueError, json.JSONDecodeError):
        return "malformed_error_body"
    detail = payload.get("detail", {}) if isinstance(payload, dict) else {}
    return str(detail.get("reason", "")) if isinstance(detail, dict) else ""
