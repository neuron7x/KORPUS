#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.ingestion import ALLOWED_TRANSITIONS  # noqa: E402
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.domain.models import ReviewState  # noqa: E402
from korpus.domain.tenancy import ALLOWED_SUBSCRIPTION_TRANSITIONS, SubscriptionStatus  # noqa: E402
from release_identity import release_tag  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402


def _matrix(states: list[object], transitions: dict[object, frozenset[object]]) -> dict[str, dict[str, bool]]:
    return {
        str(source.value): {str(target.value): target in transitions[source] for target in states}
        for source in states
    }


def main() -> int:
    review_states = list(ReviewState)
    subscription_states = list(SubscriptionStatus)
    checks = {
        "review_total": set(ALLOWED_TRANSITIONS) == set(review_states),
        "subscription_total": set(ALLOWED_SUBSCRIPTION_TRANSITIONS) == set(subscription_states),
        "rejected_terminal": not ALLOWED_TRANSITIONS[ReviewState.REJECTED],
        "canceled_terminal": not ALLOWED_SUBSCRIPTION_TRANSITIONS[SubscriptionStatus.CANCELED],
        "expired_terminal": not ALLOWED_SUBSCRIPTION_TRANSITIONS[SubscriptionStatus.EXPIRED],
        "review_no_self_loops": all(state not in ALLOWED_TRANSITIONS[state] for state in review_states),
        "terminal_subscriptions_never_reactivate": all(
            SubscriptionStatus.ACTIVE not in ALLOWED_SUBSCRIPTION_TRANSITIONS[state]
            for state in (SubscriptionStatus.CANCELED, SubscriptionStatus.EXPIRED)
        ),
    }
    failures = [name for name, ok in checks.items() if not ok]
    result = gate_payload(
        "state_contracts", status="PASS" if not failures else "FAIL",
        source_digest=compute_source_digest(ROOT), release=release_tag(), checks=checks,
        failures=failures,
        review_matrix=_matrix(review_states, ALLOWED_TRANSITIONS),
        subscription_matrix=_matrix(subscription_states, ALLOWED_SUBSCRIPTION_TRANSITIONS),
        evidence_class="EXHAUSTIVE_ENUM_MATRIX",
    )
    out = ROOT / "var/production/state-contracts-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
