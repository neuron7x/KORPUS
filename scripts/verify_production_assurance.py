#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]
from assemble_production_assurance import DEFAULT_GATES  # noqa: E402
from korpus.application.assurance_trust import trusted_fingerprints  # noqa: E402
from korpus.application.attested_evidence import verify_ed25519_attestation  # noqa: E402
from korpus.application.production_report_verification import verify_production_report  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _gate_state() -> tuple[dict[str, dict], dict[str, str]]:
    paths = {gate: ROOT / "var/production" / filename for gate, filename in DEFAULT_GATES.items()}
    return (
        {gate: _json(path) for gate, path in paths.items()},
        {
            gate: hashlib.sha256(path.read_bytes()).hexdigest()
            for gate, path in paths.items()
            if path.is_file()
        },
    )


def _checks(report_path: Path, attestation_path: Path) -> dict[str, bool]:
    report_bytes = report_path.read_bytes() if report_path.is_file() else b""
    report = json.loads(report_bytes) if report_bytes else {}
    profile_path = ROOT / "config/assurance/production-v1.json"
    profile = _json(profile_path)
    gates, hashes = _gate_state()
    trusted = trusted_fingerprints(
        ROOT / "config/assurance/trusted-assurance-signers.json",
        "production_assurance_ed25519_public_key_sha256",
        "KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256",
    )
    source, release = compute_source_digest(ROOT), release_tag()
    signed = verify_ed25519_attestation(
        report_bytes,
        manifest_name=report_path.name,
        release=release,
        attestation=_json(attestation_path),
        trusted_fingerprints=trusted,
    )
    return verify_production_report(
        report,
        profile,
        gates,
        source=source,
        release=release,
        profile_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        gate_sha256=hashes,
        attestation_verified=signed.cryptographically_valid,
        trusted_signer=signed.trusted_signer,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report", type=Path, default=ROOT / "reports/PRODUCTION_ASSURANCE_REPORT.json"
    )
    parser.add_argument(
        "--attestation",
        type=Path,
        default=ROOT / "reports/PRODUCTION_ASSURANCE_REPORT.attestation.json",
    )
    args = parser.parse_args()
    checks = _checks(args.report, args.attestation)
    failures = [name for name, ok in checks.items() if not ok]
    print(json.dumps({"valid": not failures, "checks": checks, "failures": failures}, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
