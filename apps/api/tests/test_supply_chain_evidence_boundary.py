from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.assurance_evidence import (  # noqa: E402
    artifact_manifest_bound, scanner_summary_clean, source_sbom_covers_lock, valid_cyclonedx,
)


def test_scanner_summary_status_string_alone_is_not_clean() -> None:
    assert scanner_summary_clean({"status": "PASS", "worst_exit_code": 0, "scanners": []}) is False


def test_scanner_summary_requires_every_declared_scanner_exit_zero() -> None:
    clean = {"status": "PASS", "worst_exit_code": 0, "scanners": [
        {"scanner": name, "exit_code": 0} for name in {"gitleaks", "pip-audit:runtime", "pip-audit:dev", "trivy"}
    ]}
    assert scanner_summary_clean(clean) is True
    clean["scanners"][0]["exit_code"] = 127
    assert scanner_summary_clean(clean) is False


def test_container_sbom_filename_without_cyclonedx_payload_is_not_evidence(tmp_path: Path) -> None:
    fake = tmp_path / "api-sbom.cdx.json"
    fake.write_text(json.dumps({"bomFormat": "NotCycloneDX", "specVersion": "1.6", "components": []}), encoding="utf-8")
    assert valid_cyclonedx(json.loads(fake.read_text())) is False


def test_supply_chain_manifest_is_bound_to_artifact_bytes(tmp_path: Path) -> None:
    artifact = tmp_path / "source-sbom.cdx.json"
    artifact.write_bytes(b"alpha")
    manifest = {"schema": "korpus.supply-chain-evidence.v1", "source_tree_sha256": "s", "release": "v",
                "artifacts": {artifact.name: {"sha256": __import__("hashlib").sha256(b"alpha").hexdigest(), "bytes": 5}}}
    original = {artifact.name: (artifact.read_bytes(), artifact.stat().st_size)}
    assert artifact_manifest_bound(manifest, original, source="s", release="v") is True
    artifact.write_bytes(b"omega")  # same size: only the digest can detect this mutation
    tampered = {artifact.name: (artifact.read_bytes(), artifact.stat().st_size)}
    assert artifact_manifest_bound(manifest, tampered, source="s", release="v") is False


def test_supply_chain_manifest_from_another_source_tree_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "a"; artifact.write_bytes(b"x")
    digest = __import__("hashlib").sha256(b"x").hexdigest()
    manifest = {"schema": "korpus.supply-chain-evidence.v1", "source_tree_sha256": "old", "release": "v",
                "artifacts": {"a": {"sha256": digest, "bytes": 1}}}
    assert artifact_manifest_bound(manifest, {"a": (b"x", 1)}, source="current", release="v") is False


def test_source_sbom_must_cover_every_locked_component() -> None:
    sbom = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [{"name": "a", "version": "1"}]}
    assert source_sbom_covers_lock(sbom, {"a": "1"}) is True
    assert source_sbom_covers_lock(sbom, {"a": "1", "missing": "2"}) is False
