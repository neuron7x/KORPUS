from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.assurance_evidence import (  # noqa: E402
    artifact_manifest_bound,
    scanner_summary_clean,
    source_sbom_covers_lock,
    valid_cyclonedx,
)
from korpus.application.supply_chain_scanners import (  # noqa: E402
    container_scan_marker_clean,
    scanner_marker_current,
    scanner_summary_is_ci_aggregate,
)


def test_scanner_summary_status_string_alone_is_not_clean() -> None:
    assert scanner_summary_clean({"status": "PASS", "worst_exit_code": 0, "scanners": []}) is False


def test_scanner_summary_requires_every_declared_scanner_exit_zero() -> None:
    clean = {
        "status": "PASS",
        "worst_exit_code": 0,
        "scanners": [
            {"scanner": name, "exit_code": 0}
            for name in {"gitleaks", "pip-audit:runtime", "pip-audit:dev", "trivy"}
        ],
    }
    assert scanner_summary_clean(clean) is True
    clean["scanners"][0]["exit_code"] = 127
    assert scanner_summary_clean(clean) is False


def test_container_sbom_filename_without_cyclonedx_payload_is_not_evidence(tmp_path: Path) -> None:
    fake = tmp_path / "api-sbom.cdx.json"
    fake.write_text(
        json.dumps({"bomFormat": "NotCycloneDX", "specVersion": "1.6", "components": []}),
        encoding="utf-8",
    )
    assert valid_cyclonedx(json.loads(fake.read_text())) is False


def test_supply_chain_manifest_is_bound_to_artifact_bytes(tmp_path: Path) -> None:
    artifact = tmp_path / "source-sbom.cdx.json"
    artifact.write_bytes(b"alpha")
    manifest = {
        "schema": "korpus.supply-chain-evidence.v1",
        "source_tree_sha256": "s",
        "release": "v",
        "artifacts": {
            artifact.name: {
                "sha256": __import__("hashlib").sha256(b"alpha").hexdigest(),
                "bytes": 5,
            }
        },
    }
    original = {artifact.name: (artifact.read_bytes(), artifact.stat().st_size)}
    assert artifact_manifest_bound(manifest, original, source="s", release="v") is True
    artifact.write_bytes(b"omega")  # same size: only the digest can detect this mutation
    tampered = {artifact.name: (artifact.read_bytes(), artifact.stat().st_size)}
    assert artifact_manifest_bound(manifest, tampered, source="s", release="v") is False


def test_supply_chain_manifest_from_another_source_tree_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "a"
    artifact.write_bytes(b"x")
    digest = __import__("hashlib").sha256(b"x").hexdigest()
    manifest = {
        "schema": "korpus.supply-chain-evidence.v1",
        "source_tree_sha256": "old",
        "release": "v",
        "artifacts": {"a": {"sha256": digest, "bytes": 1}},
    }
    assert (
        artifact_manifest_bound(manifest, {"a": (b"x", 1)}, source="current", release="v") is False
    )


def test_source_sbom_must_cover_every_locked_component() -> None:
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [{"name": "a", "version": "1"}],
    }
    assert source_sbom_covers_lock(sbom, {"a": "1"}) is True
    assert source_sbom_covers_lock(sbom, {"a": "1", "missing": "2"}) is False


def test_container_scan_marker_requires_both_image_scans_exit_zero() -> None:
    clean = {
        "status": "PASS",
        "worst_exit_code": 0,
        "scanners": [
            {"scanner": "trivy:api-image", "exit_code": 0},
            {"scanner": "trivy:web-image", "exit_code": 0},
        ],
    }
    assert container_scan_marker_clean(clean) is True
    clean["scanners"].pop()
    assert container_scan_marker_clean(clean) is False


def test_supply_chain_manifest_rejects_unverified_extra_artifact() -> None:
    digest = __import__("hashlib").sha256(b"x").hexdigest()
    manifest = {
        "schema": "korpus.supply-chain-evidence.v1",
        "source_tree_sha256": "s",
        "release": "v",
        "artifacts": {
            "a": {"sha256": digest, "bytes": 1},
            "unverified": {"sha256": digest, "bytes": 1},
        },
    }
    assert artifact_manifest_bound(manifest, {"a": (b"x", 1)}, source="s", release="v") is False


def test_scanner_marker_commit_must_be_one_whose_source_is_this_tree() -> None:
    """Множина прийнятних комітів — ВИМІР по репозиторію, а не одне оголошення.

    Коміт, що змінив лише звіти, лишає джерело тим самим, тож маркер сканера з нього
    ще описує це дерево. Коміт, що торкнувся джерела, — вже ні. Порожня множина не
    приймає нічого: «не змогли виміряти» не є «підходить».
    """
    marker = {"commit_sha": "old"}
    assert scanner_marker_current(marker, ("head", "reports-only")) is False
    marker["commit_sha"] = "reports-only"
    assert scanner_marker_current(marker, ("head", "reports-only")) is True
    assert scanner_marker_current(marker, ()) is False
    assert scanner_marker_current({}, ("head",)) is False


def test_a_marker_without_a_commit_is_not_accepted_by_an_empty_string_member() -> None:
    """Маркер без коміта дає `None`, і зарахувати його могла б лише множина з `None`."""
    assert scanner_marker_current({"commit_sha": ""}, ("",)) is True
    assert scanner_marker_current({"commit_sha": ""}, ("head",)) is False


def test_a_local_scan_summary_is_not_the_ci_aggregate() -> None:
    """Два виробники писали один файл; слабший ставав на місце сильнішого мовчки.

    Виміряно 06.09.2026: `security_scan.sh` писав схему 1 у `var/security/summary.json`,
    звідки предикат читає підсумок сканерів закріплених образів конвеєра. Скарга виходила
    про свіжість коміта, хоч предмет — ПОХОДЖЕННЯ, і «перезніми локально» робило гірше.
    """
    assert scanner_summary_is_ci_aggregate({"schema_version": 2}) is True
    assert scanner_summary_is_ci_aggregate({"schema_version": 1}) is False
    assert scanner_summary_is_ci_aggregate({"schema_version": "2"}) is False
    assert scanner_summary_is_ci_aggregate({}) is False
