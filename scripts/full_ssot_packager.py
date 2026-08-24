from __future__ import annotations

import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

from importlib import import_module
extract_safe_archive = import_module(f"{__package__ + chr(46) if __package__ else chr(39)*0}safe_archive_extract").extract_safe_archive

RUNTIME_PARTS = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
TOP_LEVEL_EXCLUDED = {"dist", "var"}
REGENERATED = {"DISTRIBUTION_MANIFEST.json", "FULL_SSOT_PACKAGE_RECEIPT.json"}


def included(relative: Path) -> bool:
    parts = relative.parts
    if not parts or parts[0] in TOP_LEVEL_EXCLUDED or any(part in RUNTIME_PARTS for part in parts):
        return False
    if relative.as_posix() in REGENERATED:
        return False
    if parts[:2] == ("infra", "secrets") and relative.suffix == ".txt":
        return False
    return True

def project_files(root: Path) -> list[Path]:
    return sorted(
        (path.relative_to(root) for path in root.rglob("*") if path.is_file() and included(path.relative_to(root))),
        key=Path.as_posix,
    )


def _copy(root: Path, stage: Path, paths: Iterable[Path]) -> None:
    for relative in paths:
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target)


def _zip_tree(stage: Path, archive: Path) -> None:
    files = sorted((p for p in stage.rglob("*") if p.is_file()), key=lambda p: p.relative_to(stage).as_posix())
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            relative = Path(stage.name) / path.relative_to(stage)
            info = zipfile.ZipInfo(relative.as_posix(), (1980, 1, 1, 0, 0, 0))
            mode = stat.S_IMODE(path.stat().st_mode)
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())


def _run(root: Path, *command: str) -> None:
    completed = subprocess.run([*command], cwd=root, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"{' '.join(command)} failed\n{completed.stdout}\n{completed.stderr}")


def stage_full_ssot(root: Path, stage: Path) -> dict[str, object]:
    _copy(root, stage, project_files(root))
    sys.path.insert(0, str(root / "scripts"))
    from generate_manifest import write_manifest
    release = json.loads((stage / "apps/api/src/korpus/release.json").read_text(encoding="utf-8"))["tag"]
    source = json.loads((stage / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    receipt = {
        "schema": "korpus.full-ssot-package-receipt.v2",
        "package_role": "FULL_SSOT_CANONICAL",
        "release": release,
        "source_manifest_root_sha256": source.get("root_sha256"),
        "source_manifest_files": source.get("file_count"),
        "web_dist_files": len([p for p in (stage / "apps/web/dist").rglob("*") if p.is_file()]) if (stage / "apps/web/dist").is_dir() else 0,
        "lineage_files": len([p for p in (stage / "LINEAGE").rglob("*") if p.is_file()]) if (stage / "LINEAGE").is_dir() else 0,
        "history_included": False,
        "distribution_manifest_policy": "regenerated_from_exact_staged_bytes",
    }
    (stage / "FULL_SSOT_PACKAGE_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = write_manifest(stage, stage / "DISTRIBUTION_MANIFEST.json", kind="distribution")
    receipt["distribution_records"] = manifest["file_count"]
    (stage / "FULL_SSOT_PACKAGE_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_manifest(stage, stage / "DISTRIBUTION_MANIFEST.json", kind="distribution")
    return receipt



def build(root: Path, archive: Path) -> dict[str, object]:
    root, archive = root.resolve(), archive.resolve()
    with tempfile.TemporaryDirectory(prefix="korpus-full-ssot-") as tmp_name:
        stage = Path(tmp_name) / archive.stem
        stage.mkdir(parents=True)
        receipt = stage_full_ssot(root, stage)
        _zip_tree(stage, archive)
        rebuild = archive.with_suffix(".rebuild.zip")
        _zip_tree(stage, rebuild)
        digest, rebuild_digest = (hashlib.sha256(path.read_bytes()).hexdigest() for path in (archive, rebuild))
        if digest != rebuild_digest:
            raise RuntimeError("deterministic rebuild SHA-256 mismatch")
        rebuild.unlink()
    _run(root, sys.executable, "scripts/verify_package.py", str(archive))
    with tempfile.TemporaryDirectory(prefix="korpus-full-ssot-post-") as tmp_name:
        unpacked = extract_safe_archive(archive, Path(tmp_name))
        _run(root, sys.executable, "scripts/verify_source_manifest.py", "--root", str(unpacked))
        _run(unpacked, sys.executable, "scripts/validate_repository.py", "--context", "FULL_SSOT_DISTRIBUTION")
        _run(root, sys.executable, "scripts/verify_current_truth.py", "--root", str(unpacked))
        _run(root, sys.executable, "scripts/verify_package_build_identity.py", "--root", str(unpacked))
    return {**receipt, "archive": archive.name, "sha256": digest, "deterministic_rebuild": True}
