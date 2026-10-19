from __future__ import annotations

import stat
import subprocess
from pathlib import Path
from typing import Any

from korpus.application.release_claim_common import file_sha256, load_object


def _distribution_record(root: Path, relative: str) -> dict[str, Any] | None:
    manifest = load_object(root / "DISTRIBUTION_MANIFEST.json")
    if not manifest or manifest.get("schema") != "korpus.distribution-manifest.v2":
        return None
    records = manifest.get("files")
    if not isinstance(records, list):
        return None
    matches = [row for row in records if isinstance(row, dict) and row.get("path") == relative]
    return matches[0] if len(matches) == 1 else None


def _distribution_admits(root: Path, relative: str) -> bool:
    path, record = root / relative, _distribution_record(root, relative)
    if not path.is_file() or record is None:
        return False
    mode = f"{stat.S_IMODE(path.stat().st_mode):04o}"
    return (
        record.get("bytes") == path.stat().st_size
        and record.get("sha256") == file_sha256(path)
        and record.get("mode") == mode
    )


def _package_identity(root: Path) -> bool:
    receipt = load_object(root / "FULL_SSOT_PACKAGE_RECEIPT.json")
    return bool(
        receipt
        and receipt.get("schema") == "korpus.full-ssot-package-receipt.v2"
        and receipt.get("package_role") == "FULL_SSOT_CANONICAL"
    )


def canonical_paths_admitted(root: Path, relatives: list[str]) -> bool:
    """Admit only Git-indexed canonical bytes or a verified-shape SSOT package."""
    if not relatives or len(relatives) != len(set(relatives)):
        return False
    if not (root / ".git").exists():
        return _package_identity(root) and all(
            _distribution_admits(root, path) for path in relatives
        )
    try:
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", *relatives],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return tracked.returncode == 0
