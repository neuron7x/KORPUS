#!/usr/bin/env python3
"""Verify independently signed, structured red-team evidence for this source/release."""

from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]
from korpus.application.assurance_trust import trusted_fingerprints  # noqa: E402
from korpus.application.attested_evidence import verify_ed25519_attestation  # noqa: E402
from korpus.application.external_redteam import evaluate_external_redteam  # noqa: E402
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

TRUST = ROOT / "config/assurance/trusted-external-signers.json"
PROFILE = ROOT / "config/assurance/redteam-production-v1.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report", type=Path, default=ROOT / "var/production/external-redteam-report.json"
    )
    parser.add_argument(
        "--attestation",
        type=Path,
        default=ROOT / "var/production/external-redteam-attestation.json",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "var/production/redteam-gate.json")
    args = parser.parse_args()
    source, release = compute_source_digest(ROOT), release_tag()
    report_bytes = args.report.read_bytes() if args.report.is_file() else b""
    report = json.loads(report_bytes) if report_bytes else {}
    attestation = (
        json.loads(args.attestation.read_text(encoding="utf-8"))
        if args.attestation.is_file()
        else {}
    )
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    content = evaluate_external_redteam(report, profile)
    trusted = trusted_fingerprints(
        TRUST, "ed25519_public_key_sha256", "KORPUS_TRUSTED_EXTERNAL_REDTEAM_SIGNER_SHA256"
    )
    signed = verify_ed25519_attestation(
        report_bytes,
        manifest_name=args.report.name,
        release=release,
        attestation=attestation,
        trusted_fingerprints=trusted,
    )
    checks = {
        "report_present": bool(report),
        "attestation_present": bool(attestation),
        "attestation_verified": signed.cryptographically_valid,
        "trusted_signer": signed.trusted_signer,
        "source_bound": report.get("source_tree_sha256") == source,
        "release_bound": report.get("release") == release,
        "independent_class": report.get("evidence_class") == "EXTERNAL_INDEPENDENT",
        "preregistered": report.get("preregistration_sha256")
        == hashlib.sha256(PROFILE.read_bytes()).hexdigest(),
        **content["checks"],
    }
    failures = [name for name, passed in checks.items() if not passed]
    payload = gate_payload(
        "redteam",
        status="PASS" if not failures else "FAIL",
        source_digest=source,
        release=release,
        checks=checks,
        failures=failures,
        evidence_class="EXTERNAL_INDEPENDENT",
        attestation_verified=signed.cryptographically_valid,
        trusted_signer=signed.trusted_signer,
        signer_fingerprint=signed.fingerprint,
        redteam=content,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
