#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from manifest_paths import source_paths

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "SOURCE_MANIFEST.json"


def main() -> int:
    if not MANIFEST.is_file():
        raise SystemExit("SOURCE_MANIFEST.json is missing")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema") != "korpus.source-manifest.v1" or manifest.get("kind") != "source":
        raise SystemExit("invalid source manifest schema")
    records = manifest.get("files")
    if not isinstance(records, list):
        raise SystemExit("invalid source manifest records")
    by_path = {str(record.get("path")): record for record in records if isinstance(record, dict)}
    authoritative = [path.as_posix() for path in source_paths(ROOT)]
    failures: list[str] = []
    if sorted(by_path) != authoritative:
        missing = sorted(set(authoritative) - set(by_path))
        extra = sorted(set(by_path) - set(authoritative))
        failures.append(f"path parity mismatch missing={missing} extra={extra}")
    for relative in authoritative:
        path = ROOT / relative
        record = by_path.get(relative, {})
        if not path.is_file():
            failures.append(f"missing source file: {relative}")
            continue
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if record.get("bytes") != len(content) or record.get("sha256") != digest:
            failures.append(f"source digest mismatch: {relative}")
    if failures:
        print(json.dumps({"valid": False, "failures": failures}, indent=2))
        return 1
    print(json.dumps({
        "valid": True,
        "files": len(authoritative),
        "root_sha256": manifest.get("root_sha256"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
