from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from korpus.application.production_assurance import evaluate_production_assurance


def verify_production_report(
    report: Mapping[str, Any],
    profile: Mapping[str, Any],
    gates: Mapping[str, Mapping[str, Any]],
    *,
    source: str,
    release: str,
    profile_sha256: str,
    gate_sha256: Mapping[str, str],
    attestation_verified: bool,
    trusted_signer: bool,
) -> dict[str, bool]:
    verdict = evaluate_production_assurance(profile, gates, source_digest=source, release=release)
    return {
        "schema": report.get("schema") == "korpus.production-assurance.v1",
        "recomputed_pass": verdict.passed,
        "status_pass": report.get("status") == "PASS" and report.get("status") == verdict.status,
        "production_authorized": report.get("production_authorized") is True and verdict.passed,
        "release_bound": report.get("release") == release,
        "source_bound": report.get("source_tree_sha256") == source,
        "profile_bound": report.get("profile_sha256") == profile_sha256,
        "gate_hashes_current": report.get("gate_sha256") == dict(gate_sha256),
        "embedded_gates_current": report.get("gates") == dict(gates),
        "checks_recomputed": report.get("checks") == dict(verdict.checks),
        "failures_recomputed": report.get("failures") == list(verdict.failures),
        "assurance_attestation_verified": attestation_verified,
        "assurance_trusted_signer": trusted_signer,
    }
