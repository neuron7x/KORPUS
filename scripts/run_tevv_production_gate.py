#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src")); sys.path.insert(0, str(ROOT / "scripts"))
from korpus.application.assurance_evidence import tevv_environment_attestation_checks  # noqa: E402
from korpus.application.assurance_trust import trusted_fingerprints  # noqa: E402
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from korpus.application.tevv import evaluate_tevv  # noqa: E402
from korpus.application.tevv_evidence import evaluate_tevv_ledger  # noqa: E402
from release_identity import release_tag  # noqa: E402
PROFILE = ROOT / "config/assurance/tevv-production-v1.json"; TRUST = ROOT / "config/assurance/trusted-assurance-signers.json"

def evaluate(evidence: dict[str, Any], profile: dict[str, Any], attestation: dict[str, Any],
             trusted: set[str], evidence_bytes: bytes, manifest_name: str) -> dict[str, Any]:
    source, release = compute_source_digest(ROOT), release_tag()
    ledger = evaluate_tevv_ledger(evidence, profile)
    metrics = ledger["metrics"]
    total, passed = int(metrics["observations"]), int(metrics["passed"])
    verdict = evaluate_tevv(passed=passed, total=total, corpus_declaration=evidence.get("corpus"),
        maximum_interval_width=float(profile["maximum_interval_width"]), minimum_observations=int(profile["minimum_observations"]))
    required = set(profile["required_attack_families"])
    attested, fingerprint = tevv_environment_attestation_checks(
        evidence_bytes, manifest_name, release, attestation, trusted)
    checks = {
        "evidence_schema": evidence.get("schema") == profile["evidence_schema"],
        "preregistered": evidence.get("preregistration_sha256") == hashlib.sha256(PROFILE.read_bytes()).hexdigest(),
        "source_bound": evidence.get("source_tree_sha256") == source,
        "release_bound": evidence.get("release") == release,
        "environment_class": evidence.get("environment_class") in profile["allowed_environment_classes"],
        **attested, **ledger["checks"],
        "tevv_admissible": verdict.admissible,
        "pass_rate": total > 0 and passed / total >= float(profile["minimum_pass_rate"]),
        "citation_integrity": int(metrics["citation_failures"]) <= int(profile["maximum_citation_failures"]),
        "leakage": int(metrics["leakage_failures"]) <= int(profile["maximum_leakage_failures"]),
        "determinism": int(metrics["determinism_failures"]) <= int(profile["maximum_determinism_failures"]),
        "null_controls": int(metrics["null_controls"]) >= int(profile["minimum_null_controls"]),
        "null_false_accepts": int(metrics["null_control_false_accepts"]) <= int(profile["maximum_null_control_false_accepts"]),
        "attack_families": required.issubset(set(metrics["attack_families"])),
    }
    failures = [name for name, ok in checks.items() if not ok]
    failures.extend(f"tevv:{reason}" for reason in verdict.reasons)
    return gate_payload("tevv", status="PASS" if not failures else "FAIL", source_digest=source, release=release,
        checks=checks, failures=failures, environment_class=evidence.get("environment_class"),
        environment_signer_fingerprint=fingerprint, tevv=verdict.as_dict(), observations=total, ledger_metrics=metrics)

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--evidence", type=Path, default=ROOT / "var/production/tevv-evidence.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/production/tevv-gate.json"); parser.add_argument("--attestation", type=Path, default=ROOT / "var/production/tevv-evidence.attestation.json")
    args = parser.parse_args(); profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    evidence_bytes = args.evidence.read_bytes() if args.evidence.is_file() else b""
    evidence = json.loads(evidence_bytes.decode("utf-8")) if evidence_bytes else {}
    attestation = json.loads(args.attestation.read_text(encoding="utf-8")) if args.attestation.is_file() else {}
    trusted = trusted_fingerprints(TRUST, "environment_ed25519_public_key_sha256", "KORPUS_TRUSTED_ENVIRONMENT_SIGNER_SHA256")
    result = evaluate(evidence, profile, attestation, trusted, evidence_bytes, args.evidence.name)
    args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
