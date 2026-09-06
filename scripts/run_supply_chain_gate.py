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
from release_identity import release_tag  # noqa: E402
from source_digest import commits_with_identical_source  # noqa: E402

PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)")
LOCKS = (ROOT / "apps/api/requirements.runtime.lock", ROOT / "apps/api/requirements.dev.lock")
TRUST = ROOT / "config/assurance/trusted-assurance-signers.json"


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    pins = hashes = 0
    locked: dict[str, str] = {}
    for path in LOCKS:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = PIN.match(line.strip())
            if match:
                pins += 1
                locked[match.group(1).lower().replace("_", "-")] = match.group(2)
            if "--hash=sha256:" in line:
                hashes += 1
    source, release = compute_source_digest(ROOT), release_tag()
    names = (
        "source-sbom.cdx.json",
        "api-sbom.cdx.json",
        "web-sbom.cdx.json",
        "var/security/summary.json",
        "var/security/ci-container-scan.json",
    )
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
        source_sbom=_json(paths[names[0]]),
        api_sbom=_json(paths[names[1]]),
        web_sbom=_json(paths[names[2]]),
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
