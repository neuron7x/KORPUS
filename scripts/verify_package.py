#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from manifest_lib.integrity import archive_modes, archive_root, file_sha256, record_failures
from manifest_lib.package_inventory import archive_inventory_failures, load_distribution_records
from package_contracts import verify_package_contracts


def _verify_tree(root: Path, records: dict[str, dict[str, object]], modes: dict[str, str]) -> list[str]:
    failures = []
    actual = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != "DISTRIBUTION_MANIFEST.json"
    )
    if sorted(records) != actual:
        failures.append(
            f"path parity mismatch missing={sorted(set(records) - set(actual))} "
            f"extra={sorted(set(actual) - set(records))}"
        )
    for relative in actual:
        record = records.get(relative, {})
        failures.extend(record_failures(root / relative, record, modes.get(relative)))
    return failures


def verify(archive: Path) -> tuple[list[str], int]:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="korpus-package-verify-") as tmp_name:
        tmp = Path(tmp_name)
        with zipfile.ZipFile(archive) as zf:
            failures.extend(archive_inventory_failures(zf))
            if failures:
                return failures, 0
            zf.extractall(tmp)
            root = archive_root(tmp)
            modes = archive_modes(zf, root.name if root != tmp else "")
        manifest_failures, records = load_distribution_records(root)
        failures.extend(manifest_failures)
        failures.extend(_verify_tree(root, records, modes))
        failures.extend(verify_package_contracts(root, modes))
        return failures, len(records) + 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    archive = parser.parse_args().archive.resolve()
    if not archive.is_file():
        raise SystemExit(f"archive missing: {archive}")
    try:
        failures, files = verify(archive)
    except (RuntimeError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        failures, files = [str(exc)], 0
    payload = {"valid": not failures, "archive": str(archive), "sha256": file_sha256(archive), "files": files}
    if failures:
        payload["failures"] = failures
    print(json.dumps(payload, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
