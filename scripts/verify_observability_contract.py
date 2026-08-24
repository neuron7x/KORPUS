#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from prometheus_client import CollectorRegistry

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.infrastructure.observability import Observability  # noqa: E402
from release_identity import release_tag  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402

FORBIDDEN_LABELS = {"subject", "tenant", "tenant_id", "account_id", "request_id", "query", "text", "token", "email"}


def main() -> int:
    obs = Observability(registry=CollectorRegistry())
    try:
        collectors = {
            name: tuple(getattr(value, "_labelnames", ()))
            for name, value in vars(obs).items()
            if hasattr(value, "_labelnames")
        }
        leaked = {
            name: sorted(FORBIDDEN_LABELS.intersection(labels))
            for name, labels in collectors.items()
            if FORBIDDEN_LABELS.intersection(labels)
        }
        checks = {
            "no_identity_or_user_text_labels": not leaked,
            "security_labels_bounded": collectors.get("security_events") == ("event", "outcome"),
            "request_id_not_metric_label": all("request_id" not in labels for labels in collectors.values()),
            "telemetry_state_explicit": obs.telemetry_status().get("traces") in {"DISABLED", "ACTIVE", "REQUESTED_NOT_ACTIVE"},
        }
    finally:
        obs.close()
    failures = [name for name, ok in checks.items() if not ok]
    result = gate_payload(
        "observability", status="PASS" if not failures else "FAIL",
        source_digest=compute_source_digest(ROOT), release=release_tag(), checks=checks,
        failures=failures, metric_labels=collectors, forbidden_label_hits=leaked,
        evidence_class="STATIC_PLUS_RUNTIME_METRIC_CONTRACT",
    )
    out = ROOT / "var/production/observability-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
