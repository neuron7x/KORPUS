#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "apps/api/src")]
from korpus.application.provenance import compute_source_digest
from manifest_lib.integrity import manifest_failures, mode_string, record_failures
from manifest_paths import source_paths
from release_identity import release_tag


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
    authoritative = [p.as_posix() for p in source_paths(root)]
    failures = manifest_failures(manifest, records)
    if sorted(by_path) != authoritative:
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


def bound_report(root: Path) -> dict[str, object]:
    payload = verify(root)
    payload["schema"] = "korpus.source-manifest-verification.v1"
    payload["status"] = "PASS" if payload["valid"] else "FAIL"
    payload["release"] = release_tag(root)
    payload["source_tree_sha256"] = compute_source_digest(root)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    payload = bound_report(root)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
