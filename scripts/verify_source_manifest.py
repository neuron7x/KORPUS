#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from manifest_lib.integrity import manifest_failures, mode_string, record_failures
from manifest_paths import source_paths

ROOT = Path(__file__).resolve().parents[1]


def verify(root: Path) -> dict[str, object]:
    path = root / "SOURCE_MANIFEST.json"
    if not path.is_file():
        return {"valid": False, "failures": ["SOURCE_MANIFEST.json is missing"]}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "korpus.source-manifest.v2" or manifest.get("kind") != "source":
        return {"valid": False, "failures": ["invalid source manifest schema"]}
    records = manifest.get("files")
    if not isinstance(records, list):
        return {"valid": False, "failures": ["invalid source manifest records"]}
    by_path = {str(record.get("path")): record for record in records if isinstance(record, dict)}
    authoritative = (
        [p.as_posix() for p in source_paths(root)] if (root / ".git").exists() else sorted(by_path)
    )
    failures = manifest_failures(manifest, records)
    if sorted(by_path) != authoritative:
        failures.append(
            f"path parity mismatch missing={sorted(set(authoritative) - set(by_path))} extra={sorted(set(by_path) - set(authoritative))}"
        )
    for relative in authoritative:
        file, record = root / relative, by_path.get(relative, {})
        if not file.is_file():
            failures.append(f"missing source file: {relative}")
        else:
            failures.extend(
                f"source {item}"
                for item in record_failures(file, record, mode_string(file, source=True))
            )
    return {
        "valid": not failures,
        "files": len(authoritative),
        "root_sha256": manifest.get("root_sha256"),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    payload = verify(args.root.resolve())
    print(json.dumps(payload, indent=2))
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
