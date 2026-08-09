#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_root(tmp: Path) -> Path:
    roots = [p for p in tmp.iterdir() if p.is_dir()]
    return roots[0] if len(roots) == 1 else tmp


def _load_records(root: Path, failures: list[str]) -> dict[str, dict[str, object]]:
    path = root / "DISTRIBUTION_MANIFEST.json"
    if not path.is_file():
        raise RuntimeError("DISTRIBUTION_MANIFEST.json missing from archive")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "korpus.distribution-manifest.v1":
        failures.append("invalid distribution manifest schema")
    records = manifest.get("files")
    if not isinstance(records, list):
        failures.append("invalid distribution manifest records")
        return {}
    return {str(record.get("path")): record for record in records if isinstance(record, dict)}


def _verify_tree(root: Path, records: dict[str, dict[str, object]]) -> list[str]:
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
        path = root / relative
        if record.get("bytes") != path.stat().st_size or record.get("sha256") != sha256(path):
            failures.append(f"digest mismatch: {relative}")
    return failures


def verify(archive: Path) -> tuple[list[str], int]:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="korpus-package-verify-") as tmp_name:
        tmp = Path(tmp_name)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp)
        root = _archive_root(tmp)
        records = _load_records(root, failures)
        failures.extend(_verify_tree(root, records))
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
    payload = {"valid": not failures, "archive": str(archive), "sha256": sha256(archive), "files": files}
    if failures:
        payload["failures"] = failures
    print(json.dumps(payload, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
