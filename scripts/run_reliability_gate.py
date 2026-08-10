#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src")); sys.path.insert(0, str(ROOT / "scripts"))
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.production_reliability import evaluate_reliability_evidence  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def main() -> int:
    internal = _read(ROOT / "var/production/reliability_internal-gate.json")
    chaos = _read(ROOT / "var/chaos-matrix.json"); load = _read(ROOT / "var/load-probe.json")
    recovery = _read(ROOT / "var/recovery-report.json")
    source, release = compute_source_digest(ROOT), release_tag()
    checks = evaluate_reliability_evidence(internal, chaos, load, recovery, source=source, release=release)
    failures = [name for name, ok in checks.items() if not ok]
    result = gate_payload(
        "reliability", status="PASS" if not failures else "FAIL", source_digest=source,
        release=release, checks=checks, failures=failures,
        evidence_class="LIVE_PLUS_FAULT_INJECTION_REQUIRED",
        load_metrics={name: load.get(name, {}) for name in ("load", "spike", "soak")},
        chaos_cases=len(chaos.get("cases", ())), recovery_status=recovery.get("status", "NOT_EXECUTED"),
    )
    out = ROOT / "var/production/reliability-gate.json"; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
