#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))
from korpus.application.assurance_evidence import evaluate_supply_chain_evidence  # noqa: E402
from korpus.application.assurance_trust import trusted_fingerprints  # noqa: E402
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from korpus.application.sbom_evidence import SbomCiEvidence  # noqa: E402
from release_identity import release_tag  # noqa: E402
from source_digest import commits_with_identical_source, tracked_tree_digest  # noqa: E402

PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)")
LOCKS = (ROOT / "apps/api/requirements.runtime.lock", ROOT / "apps/api/requirements.dev.lock")
TRUST = ROOT / "config/assurance/trusted-assurance-signers.json"
EVIDENCE_NAMES = (
    "var/ci-evidence/source-sbom.cdx.json",
    "var/ci-evidence/api-sbom.cdx.json",
    "var/ci-evidence/web-sbom.cdx.json",
    "var/security/summary.json",
    "var/security/ci-container-scan.json",
    "var/ci-evidence/source-sbom-receipt.json",
    "var/ci-evidence/container-sbom-receipt.json",
    "var/ci-evidence/assurance-admission.json",
)


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _lock(path: Path) -> tuple[dict[str, str], int]:
    locked: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if match := PIN.match(line.strip()):
            locked[match.group(1).lower().replace("_", "-")] = match.group(2)
    return locked, sum("--hash=sha256:" in line for line in lines)


def _lock_inventory() -> tuple[int, int, dict[str, str], dict[str, str]]:
    runtime, runtime_hashes = _lock(LOCKS[0])
    development, development_hashes = _lock(LOCKS[1])
    locked = {**runtime, **development}
    return len(runtime) + len(development), runtime_hashes + development_hashes, locked, runtime


def _sbom_evidence(
    paths: dict[str, Path], raw: dict[str, bytes], api_locked: dict[str, str]
) -> SbomCiEvidence:
    names = EVIDENCE_NAMES
    return SbomCiEvidence(
        source_sbom=_json(paths[names[0]]),
        api_sbom=_json(paths[names[1]]),
        web_sbom=_json(paths[names[2]]),
        api_locked=api_locked,
        source_receipt=_json(paths[names[5]]),
        source_receipt_bytes=raw[names[5]],
        container_receipt=_json(paths[names[6]]),
        container_receipt_bytes=raw[names[6]],
        admission=_json(paths[names[7]]),
        source_tree_sha256=tracked_tree_digest("HEAD"),
    )


def main() -> int:
    pins, hashes, locked, api_locked = _lock_inventory()
    source, release = compute_source_digest(ROOT), release_tag()
    names = EVIDENCE_NAMES
    paths = {name: ROOT / name for name in names}
    raw = {name: path.read_bytes() if path.is_file() else b"" for name, path in paths.items()}
    manifest_path = ROOT / "var/production/supply-chain-evidence-manifest.json"
    attestation_path = ROOT / "var/production/supply-chain-evidence.attestation.json"
    trusted = trusted_fingerprints(
        TRUST, "supply_chain_ed25519_public_key_sha256", "KORPUS_TRUSTED_SUPPLY_CHAIN_SIGNER_SHA256"
    )
    checks, completeness, fingerprint = evaluate_supply_chain_evidence(
        pins=pins,
        hashes=hashes,
        locked=locked,
        scan=_json(paths[names[3]]),
        container_scan=_json(paths[names[4]]),
        sbom_ci=_sbom_evidence(paths, raw, api_locked),
        manifest=_json(manifest_path),
        artifact_bytes=raw,
        source=source,
        release=release,
        attestation=_json(attestation_path),
        trusted=trusted,
        manifest_bytes=manifest_path.read_bytes() if manifest_path.is_file() else b"",
        accepted_commits=commits_with_identical_source(),
    )
    failures = [name for name, ok in checks.items() if not ok]
    result = gate_payload(
        "supply_chain",
        status="PASS" if not failures else "FAIL",
        source_digest=source,
        release=release,
        checks=checks,
        failures=failures,
        evidence_class="ATTESTED_CI_SCANNERS_PLUS_CONTAINER_SBOM",
        completeness=completeness,
        pinned_records=pins,
        hashed_records=hashes,
        signer_fingerprint=fingerprint,
    )
    out = ROOT / "var/production/supply_chain-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
