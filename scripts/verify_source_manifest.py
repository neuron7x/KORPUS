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
    # Path parity has to come from the tree, not from the manifest. Falling back to
    # `sorted(by_path)` compared the manifest with itself: in an unpacked archive — the one
    # place this check is the only thing standing between a reader and an injected file —
    # `scripts/backdoor.py` added to the tree passed with valid: true, because the manifest
    # did not list it and the manifest was the authority. Measured 2026-08-29.
    authoritative = [p.as_posix() for p in source_paths(root)]
    failures = manifest_failures(manifest, records)
    if sorted(by_path) != authoritative:
        # `missing=` read as "missing from the tree" and named the exact opposite: files
        # that ARE in the tree and are not described. On an unpacked archive that is the
        # injected-file case, and the word pointed the reader away from it.
        failures.append(
            "path parity mismatch "
            f"in_tree_not_in_manifest={sorted(set(authoritative) - set(by_path))} "
            f"in_manifest_not_in_tree={sorted(set(by_path) - set(authoritative))}"
        )
    for relative in authoritative:
        file, record = root / relative, by_path.get(relative)
        if not file.is_file():
            failures.append(f"missing source file: {relative}")
        elif record is None:
            # The parity line above already names this file. Running record_failures on an
            # empty record produced `source mode mismatch: None expected=None actual=0644`
            # once per unlisted file — a wall of messages naming no path, in front of the
            # one line that did. Measured on a copy carrying 29 uncommitted files.
            continue
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
