"""The final ZIP must prove its embedded source manifest against packaged bytes."""
from __future__ import annotations

import zipfile
from pathlib import Path

from scripts.generate_manifest import write_manifest
from scripts.verify_package import verify


def _source(root: Path, relative: str, content: str, mode: int = 0o644) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


def _add_package_only_files(root: Path) -> None:
    _source(root, "PACKAGE_BOUNDARY.md", "distribution boundary\n")
    _source(root, "reports/RESEARCH_ASSURANCE_REPORT.json", '{"status":"PASS"}\n')
    _source(root, "evidence/sealed.json", '{"sealed":true}\n')
    _source(root, "history.bundle", "bundle fixture\n")


def _seal(root: Path, archive: Path) -> None:
    write_manifest(root, root / "DISTRIBUTION_MANIFEST.json", kind="distribution")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(root).as_posix())


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "package"
    root.mkdir()
    policy = _source(root, "apps/api/src/korpus/policy.py", "threshold = 1.0\n")
    _source(root, "source-sbom.cdx.json", '{"bomFormat":"CycloneDX"}\n')
    write_manifest(root, root / "SOURCE_MANIFEST.json", kind="source")
    return root, policy


def test_valid_source_snapshot_allows_package_only_evidence(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    _add_package_only_files(root)
    archive = tmp_path / "valid.zip"
    _seal(root, archive)

    failures, _ = verify(archive)
    assert failures == []


def test_stale_embedded_source_manifest_is_rejected(tmp_path: Path) -> None:
    root, policy = _fixture(tmp_path)
    policy.write_text("threshold = 0.0\n", encoding="utf-8")
    archive = tmp_path / "stale.zip"
    _seal(root, archive)

    failures, _ = verify(archive)
    assert any("source digest mismatch" in failure for failure in failures)


def test_source_file_omitted_from_embedded_manifest_is_rejected(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    _source(root, "apps/api/src/korpus/unmanifested.py", "NEW = True\n")
    archive = tmp_path / "omitted.zip"
    _seal(root, archive)

    failures, _ = verify(archive)
    assert any("path parity mismatch" in failure for failure in failures)
    assert any("unmanifested.py" in failure for failure in failures)


def test_live_tracked_sbom_overwrite_is_rejected(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    sbom = root / "source-sbom.cdx.json"
    sbom.write_text('{"bomFormat":"CycloneDX","changed":true}\n', encoding="utf-8")
    archive = tmp_path / "dirty-sbom.zip"
    _seal(root, archive)

    failures, _ = verify(archive)
    assert any("source digest mismatch: source-sbom.cdx.json" in failure for failure in failures)


def test_source_mode_drift_is_rejected_from_archive_metadata(tmp_path: Path) -> None:
    root = tmp_path / "package"
    root.mkdir()
    executable = _source(root, "scripts/run.py", "#!/usr/bin/env python3\n", 0o755)
    write_manifest(root, root / "SOURCE_MANIFEST.json", kind="source")
    executable.chmod(0o644)
    archive = tmp_path / "mode.zip"
    _seal(root, archive)

    failures, _ = verify(archive)
    assert any("source mode mismatch" in failure for failure in failures)
