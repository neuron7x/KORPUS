#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]
from korpus.application.assurance_evidence import attestation_checks  # noqa: E402
from korpus.application.assurance_trust import trusted_fingerprints  # noqa: E402
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from korpus.application.tevv import evaluate_tevv  # noqa: E402
from korpus.application.tevv_assessor import assessor_identity_valid
from korpus.application.tevv_evidence import evaluate_tevv_ledger  # noqa: E402
from korpus.application.tevv_profile_contracts import validate_tevv_profile  # noqa: E402
from release_identity import release_tag  # noqa: E402
PROFILE = ROOT / "config/assurance/tevv-production-v1.json"; TRUST = ROOT / "config/assurance/trusted-assurance-signers.json"
def evaluate(evidence: dict[str, Any], profile: dict[str, Any], attestation: dict[str, Any],
             trusted: set[str], evidence_bytes: bytes, manifest_name: str) -> dict[str, Any]:
    source, release = compute_source_digest(ROOT), release_tag(); policy = validate_tevv_profile(profile)
    ledger = evaluate_tevv_ledger(evidence, profile); metrics = ledger["metrics"]; total, passed = metrics["observations"], metrics["passed"]
    tevv = evaluate_tevv(passed=passed, total=total, corpus_declaration=evidence.get("corpus"),
        maximum_interval_width=policy["maximum_interval_width"], minimum_observations=policy["minimum_observations"])
    attested, attestation_verdict = attestation_checks(evidence_bytes, manifest_name, release, attestation, trusted, "assessor")
    checks = {
        "evidence_schema": evidence.get("schema") == profile["evidence_schema"],
        "preregistered": evidence.get("preregistration_sha256") == hashlib.sha256(PROFILE.read_bytes()).hexdigest(),
        "source_bound": evidence.get("source_tree_sha256") == source, "release_bound": evidence.get("release") == release,
        "environment_class": evidence.get("environment_class") in profile["allowed_environment_classes"],
        "independent_class": evidence.get("evidence_class") == profile["required_evidence_class"],
        "assessor_structured": assessor_identity_valid(evidence), **attested, **ledger["checks"], "tevv_admissible": tevv.admissible,
        "pass_rate": total > 0 and passed / total >= policy["minimum_pass_rate"],
        "citation_integrity": metrics["citation_failures"] <= policy["maximum_citation_failures"],
        "leakage": metrics["leakage_failures"] <= policy["maximum_leakage_failures"],
        "determinism": metrics["determinism_failures"] <= policy["maximum_determinism_failures"],
        "null_controls": metrics["null_controls"] >= policy["minimum_null_controls"],
        "null_false_accepts": metrics["null_control_false_accepts"] <= policy["maximum_null_control_false_accepts"],
        "attack_families": set(profile["required_attack_families"]).issubset(set(metrics["attack_families"])),
    }
    failures = [name for name, ok in checks.items() if not ok] + [f"tevv:{reason}" for reason in tevv.reasons]
    return gate_payload("tevv", status="PASS" if not failures else "FAIL", source_digest=source, release=release, checks=checks,
        failures=failures, environment_class=evidence.get("environment_class"), assessor_signer_fingerprint=attestation_verdict.fingerprint,
        tevv=tevv.as_dict(), observations=total, ledger_metrics=metrics)

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--evidence", type=Path, default=ROOT / "var/production/tevv-evidence.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/production/tevv-gate.json"); parser.add_argument("--attestation", type=Path, default=ROOT / "var/production/tevv-evidence.attestation.json")
    args = parser.parse_args(); profile = json.loads(PROFILE.read_text(encoding="utf-8")); evidence_bytes = args.evidence.read_bytes() if args.evidence.is_file() else b""
    evidence = json.loads(evidence_bytes.decode("utf-8")) if evidence_bytes else {}; attestation = json.loads(args.attestation.read_text(encoding="utf-8")) if args.attestation.is_file() else {}
    trusted = trusted_fingerprints(TRUST, "tevv_ed25519_public_key_sha256", "KORPUS_TRUSTED_TEVV_SIGNER_SHA256")
    result = evaluate(evidence, profile, attestation, trusted, evidence_bytes, args.evidence.name); args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["status"] == "PASS" else 1
if __name__ == "__main__": raise SystemExit(main())
