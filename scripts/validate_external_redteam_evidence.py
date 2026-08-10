#!/usr/bin/env python3
"""Verify independently signed red-team evidence and bind it to this source/release."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src")); sys.path.insert(0, str(ROOT / "scripts"))
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

TRUST = ROOT / "config/assurance/trusted-external-signers.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ROOT / "var/production/external-redteam-report.json")
    parser.add_argument("--attestation", type=Path, default=ROOT / "var/production/external-redteam-attestation.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/production/redteam-gate.json")
    args = parser.parse_args()
    source = compute_source_digest(ROOT); release = release_tag()
    report = json.loads(args.report.read_text(encoding="utf-8")) if args.report.is_file() else {}
    attestation = json.loads(args.attestation.read_text(encoding="utf-8")) if args.attestation.is_file() else {}
    trusted = set(json.loads(TRUST.read_text(encoding="utf-8")).get("ed25519_public_key_sha256", ()))
    verified = False
    if report and attestation:
        completed = subprocess.run(
            [sys.executable, "scripts/release_attestation.py", "verify", "--manifest", str(args.report), "--attestation", str(args.attestation)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        verified = completed.returncode == 0
    fingerprint = str(attestation.get("public_key_sha256", ""))
    checks = {
        "report_present": bool(report),
        "attestation_present": bool(attestation),
        "attestation_verified": verified,
        "trusted_signer": bool(fingerprint) and fingerprint in trusted,
        "source_bound": report.get("source_tree_sha256") == source,
        "release_bound": report.get("release") == release,
        "independent_class": report.get("evidence_class") == "EXTERNAL_INDEPENDENT",
        "pentest_pass": report.get("status") == "PASS",
    }
    failures = [name for name, passed in checks.items() if not passed]
    payload = gate_payload(
        "redteam", status="PASS" if not failures else "FAIL", source_digest=source, release=release,
        checks=checks, failures=failures, evidence_class="EXTERNAL_INDEPENDENT",
        attestation_verified=verified, trusted_signer=checks["trusted_signer"], signer_fingerprint=fingerprint,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
