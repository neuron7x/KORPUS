#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.production_assurance import gate_payload  # noqa: E402
from release_identity import release_tag  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402

PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)")
LOCKS = (ROOT / "apps/api/requirements.runtime.lock", ROOT / "apps/api/requirements.dev.lock")


def main() -> int:
    pins = 0
    hashes = 0
    for path in LOCKS:
        for line in path.read_text(encoding="utf-8").splitlines():
            if PIN.match(line.strip()):
                pins += 1
            if "--hash=sha256:" in line:
                hashes += 1
    scan_path = ROOT / "var/security/summary.json"
    scan = json.loads(scan_path.read_text(encoding="utf-8")) if scan_path.is_file() else {}
    source_sbom = ROOT / "source-sbom.cdx.json"
    container_sboms = [ROOT / "api-sbom.cdx.json", ROOT / "web-sbom.cdx.json"]
    checks = {
        "exact_pins_have_hashes": pins > 0 and hashes == pins,
        "source_sbom": source_sbom.is_file(),
        "security_scanners_executed_clean": scan.get("status") == "PASS",
        "container_sboms": all(path.is_file() for path in container_sboms),
    }
    failures = [name for name, ok in checks.items() if not ok]
    completeness = "COMPLETE" if not failures else "PARTIAL"
    result = gate_payload(
        "supply_chain", status="PASS" if not failures else "FAIL",
        source_digest=compute_source_digest(ROOT), release=release_tag(), checks=checks,
        failures=failures, evidence_class="LOCK_PLUS_SCANNERS_PLUS_CONTAINER_SBOM",
        completeness=completeness, pinned_records=pins, hashed_records=hashes,
        scanner_summary=scan,
    )
    out = ROOT / "var/production/supply_chain-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
