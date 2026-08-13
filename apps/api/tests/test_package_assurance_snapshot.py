"""The final ZIP must re-verify its embedded research assurance against packaged source."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from korpus.application.provenance import compute_source_digest
from scripts.assurance_snapshot_contract import (
    RESEARCH_REPORT_PATH,
    SNAPSHOT_SCHEMA,
    canonical_snapshot_paths,
)
from scripts.generate_manifest import write_manifest
from scripts.source_digest import source_tree_digest
from scripts.verify_package import verify

RELEASE = "v0.1.1"


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _source(root: Path) -> None:
    _write(root, "apps/api/src/korpus/policy.py", "threshold = 1.0\n")
    _write(
        root,
        "apps/api/src/korpus/release.json",
        json.dumps({"schema": "korpus.release-identity.v1", "tag": RELEASE}) + "\n",
    )
    write_manifest(root, root / "SOURCE_MANIFEST.json", kind="source")


def _snapshot(
    root: Path,
    *,
    release: str = RELEASE,
    claimed_source: str | None = None,
    claimed_evidence_source: str | None = None,
) -> None:
    research = {
        "status": "PASS",
        "source_tree_sha256": claimed_source or source_tree_digest(root=root),
        "evidence_source_sha256": claimed_evidence_source or compute_source_digest(root),
    }
    _write(root, RESEARCH_REPORT_PATH, json.dumps(research) + "\n")

    records: list[dict[str, object]] = []
    for relative in canonical_snapshot_paths():
        path = root / relative
        if relative != RESEARCH_REPORT_PATH:
            path = _write(root, relative, f"evidence:{relative}\n")
        content = path.read_bytes()
        records.append(
            {
                "path": relative,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    payload = {
        "schema": SNAPSHOT_SCHEMA,
        "release": release,
        "status": "PASS",
        "records": records,
    }
    _write(root, "reports/ASSURANCE_SNAPSHOT.json", json.dumps(payload) + "\n")


def _archive(root: Path, target: Path) -> Path:
    write_manifest(root, root / "DISTRIBUTION_MANIFEST.json", kind="distribution")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(root).as_posix())
    return target


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "package"
    root.mkdir()
    _source(root)
    _snapshot(root)
    return root


def test_exact_packaged_assurance_passes(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    failures, _ = verify(_archive(root, tmp_path / "valid.zip"))
    assert failures == []


def test_report_changed_after_snapshot_is_rejected_even_with_fresh_distribution_manifest(
    tmp_path: Path,
) -> None:
    root = _fixture(tmp_path)
    report = root / canonical_snapshot_paths()[1]
    report.write_text("changed after snapshot verification\n", encoding="utf-8")
    failures, _ = verify(_archive(root, tmp_path / "stale-report.zip"))
    assert any("snapshot record mismatch" in failure for failure in failures)


def test_forged_report_and_fresh_snapshot_cannot_claim_another_source_tree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "package"
    root.mkdir()
    _source(root)
    _snapshot(root, claimed_source="b" * 64)
    failures, _ = verify(_archive(root, tmp_path / "forged-source.zip"))
    assert "assurance source digest does not match packaged source" in failures


def test_forged_report_and_fresh_snapshot_cannot_claim_another_evidence_source(
    tmp_path: Path,
) -> None:
    root = tmp_path / "package"
    root.mkdir()
    _source(root)
    _snapshot(root, claimed_evidence_source="b" * 64)
    failures, _ = verify(_archive(root, tmp_path / "forged-evidence.zip"))
    assert "assurance evidence source digest does not match packaged source" in failures


def test_missing_canonical_packaged_report_is_rejected(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    (root / canonical_snapshot_paths()[-1]).unlink()
    failures, _ = verify(_archive(root, tmp_path / "missing-report.zip"))
    assert any("snapshot record mismatch" in failure for failure in failures)


def test_snapshot_release_must_match_packaged_release_identity(tmp_path: Path) -> None:
    root = tmp_path / "package"
    root.mkdir()
    _source(root)
    _snapshot(root, release="v9.9.9")
    failures, _ = verify(_archive(root, tmp_path / "wrong-release.zip"))
    assert "assurance snapshot release/status mismatch" in failures


def test_separately_governed_report_does_not_expand_research_snapshot(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _write(
        root,
        "reports/PRODUCTION_ASSURANCE_REPORT.json",
        '{"schema":"korpus.production-assurance.v1","status":"FAIL"}\n',
    )
    failures, _ = verify(_archive(root, tmp_path / "extra-report.zip"))
    assert failures == []
