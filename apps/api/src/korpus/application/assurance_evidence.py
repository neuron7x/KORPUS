from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from typing import Any

from korpus.application.attested_evidence import AttestationVerdict, verify_ed25519_attestation
from korpus.application.production_reliability import evaluate_reliability_evidence
from korpus.application.supply_chain_scanners import (
    container_scan_marker_clean,
    scanner_marker_current,
    scanner_summary_clean,
    scanner_summary_is_ci_aggregate,
)


def attestation_checks(
    data: bytes,
    name: str,
    release: str,
    attestation: Mapping[str, Any],
    trusted: Collection[str],
    prefix: str,
) -> tuple[dict[str, bool], AttestationVerdict]:
    verdict = verify_ed25519_attestation(
        data,
        manifest_name=name,
        release=release,
        attestation=attestation,
        trusted_fingerprints=trusted,
    )
    return {
        f"{prefix}_attestation_verified": verdict.cryptographically_valid,
        f"{prefix}_trusted_signer": verdict.trusted_signer,
    }, verdict


def valid_cyclonedx(data: Mapping[str, Any]) -> bool:
    return (
        data.get("bomFormat") == "CycloneDX"
        and bool(str(data.get("specVersion", "")))
        and isinstance(data.get("components", []), list)
    )


def source_sbom_covers_lock(data: Mapping[str, Any], locked: Mapping[str, str]) -> bool:
    if not valid_cyclonedx(data):
        return False
    components = {
        (str(item.get("name", "")).lower().replace("_", "-"), str(item.get("version", "")))
        for item in data.get("components", ())
        if isinstance(item, Mapping)
    }
    return all((name, version) in components for name, version in locked.items())


def artifact_manifest_bound(
    manifest: Mapping[str, Any],
    artifacts: Mapping[str, tuple[bytes, int]],
    *,
    source: str,
    release: str,
) -> bool:
    declared = manifest.get("artifacts", {})
    if not isinstance(declared, Mapping):
        return False
    return (
        manifest.get("schema") == "korpus.supply-chain-evidence.v1"
        and manifest.get("source_tree_sha256") == source
        and manifest.get("release") == release
        and set(declared) == set(artifacts)
        and all(
            isinstance(declared.get(name), Mapping)
            and declared[name].get("sha256") == hashlib.sha256(data).hexdigest()
            and declared[name].get("bytes") == size
            for name, (data, size) in artifacts.items()
        )
    )


def evaluate_attested_reliability(
    internal: Mapping[str, Any],
    chaos: Mapping[str, Any],
    load: Mapping[str, Any],
    recovery: Mapping[str, Any],
    *,
    source: str,
    release: str,
    load_bytes: bytes,
    recovery_bytes: bytes,
    load_attestation: Mapping[str, Any],
    recovery_attestation: Mapping[str, Any],
    trusted: Collection[str],
) -> tuple[dict[str, bool], str, str]:
    checks = evaluate_reliability_evidence(
        internal, chaos, load, recovery, source=source, release=release
    )
    load_checks, load_verdict = attestation_checks(
        load_bytes, "load-probe.json", release, load_attestation, trusted, "load"
    )
    recovery_checks, recovery_verdict = attestation_checks(
        recovery_bytes, "recovery-report.json", release, recovery_attestation, trusted, "recovery"
    )
    checks.update(load_checks)
    checks.update(recovery_checks)
    return checks, load_verdict.fingerprint, recovery_verdict.fingerprint


def evaluate_supply_chain_evidence(
    *,
    pins: int,
    hashes: int,
    locked: Mapping[str, str],
    scan: Mapping[str, Any],
    container_scan: Mapping[str, Any],
    source_sbom: Mapping[str, Any],
    api_sbom: Mapping[str, Any],
    web_sbom: Mapping[str, Any],
    manifest: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    source: str,
    release: str,
    attestation: Mapping[str, Any],
    trusted: Collection[str],
    manifest_bytes: bytes,
    accepted_commits: Collection[str],
) -> tuple[dict[str, bool], str, str]:
    artifacts = {name: (data, len(data)) for name, data in artifact_bytes.items()}
    attested_checks, verdict = attestation_checks(
        manifest_bytes,
        "supply-chain-evidence-manifest.json",
        release,
        attestation,
        trusted,
        "evidence",
    )
    checks = {
        "exact_pins_have_hashes": pins > 0 and hashes == pins,
        "source_sbom_lock_complete": source_sbom_covers_lock(source_sbom, locked),
        "security_summary_is_ci_aggregate": scanner_summary_is_ci_aggregate(scan),
        "security_scanners_executed_clean": scanner_summary_clean(scan),
        "security_scanners_current_commit": scanner_marker_current(scan, accepted_commits),
        "container_scanners_executed_clean": container_scan_marker_clean(container_scan),
        "container_scanners_current_commit": scanner_marker_current(
            container_scan, accepted_commits
        ),
        "container_sboms_valid": valid_cyclonedx(api_sbom) and valid_cyclonedx(web_sbom),
        "evidence_manifest_bound": artifact_manifest_bound(
            manifest, artifacts, source=source, release=release
        ),
        **attested_checks,
    }
    failures = [name for name, ok in checks.items() if not ok]
    return checks, "COMPLETE" if not failures else "PARTIAL", verdict.fingerprint


def tevv_environment_attestation_checks(
    evidence_bytes: bytes,
    evidence_name: str,
    release: str,
    attestation: Mapping[str, Any],
    trusted: Collection[str],
) -> tuple[dict[str, bool], str]:
    checks, verdict = attestation_checks(
        evidence_bytes, evidence_name, release, attestation, trusted, "environment"
    )
    return checks, verdict.fingerprint
