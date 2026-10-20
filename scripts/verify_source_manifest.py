#!/usr/bin/env python3
import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "apps/api/src")]
from korpus.application.final_release_evidence import strict_signed_json_object
from korpus.application.provenance import compute_source_digest
from manifest_lib.integrity import manifest_failures, mode_string, record_failures
from manifest_paths import source_included, source_paths
from release_identity import release_tag

_MANIFEST_FIELDS = frozenset(
    {"schema", "kind", "manifest_self_excluded", "file_count", "root_sha256", "files"}
)
_RECORD_FIELDS = frozenset({"path", "bytes", "sha256", "mode"})


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _structure_failures(manifest: Mapping[str, Any], records: list[Any]) -> list[str]:
    """Reject structurally ambiguous manifests before path-indexing or hashing."""
    if set(manifest) != _MANIFEST_FIELDS:
        return ["unexpected or absent source manifest header field"]
    if manifest.get("manifest_self_excluded") is not True:
        return ["source manifest must exclude its own bytes"]
    if type(manifest.get("file_count")) is not int or manifest["file_count"] != len(records):
        return ["source manifest file_count is not an exact integer count"]
    if not _sha256(manifest.get("root_sha256")):
        return ["source manifest root_sha256 is malformed"]

    paths: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != _RECORD_FIELDS:
            return [f"invalid source manifest record fields at index {index}"]
        name = record.get("path")
        if not isinstance(name, str) or not name or chr(92) in name:
            return [f"invalid source manifest path at index {index}"]
        canonical = PurePosixPath(name)
        if (
            canonical.is_absolute()
            or ".." in canonical.parts
            or canonical.as_posix() != name
            or not source_included(Path(name))
        ):
            return [f"noncanonical or excluded source manifest path at index {index}"]
        if type(record.get("bytes")) is not int or record["bytes"] < 0:
            return [f"invalid source manifest byte count at index {index}"]
        if not _sha256(record.get("sha256")):
            return [f"invalid source manifest SHA-256 at index {index}"]
        if record.get("mode") not in ("0644", "0755"):
            return [f"invalid source manifest mode at index {index}"]
        paths.append(name)

    if len(paths) != len(set(paths)):
        return ["duplicate source manifest path"]
    if paths != sorted(paths):
        return ["source manifest records are not in canonical path order"]
    return []


def verify(root: Path) -> dict[str, object]:
    path = root / "SOURCE_MANIFEST.json"
    if not path.is_file():
        return {"valid": False, "failures": ["SOURCE_MANIFEST.json is missing"]}
    try:
        manifest = dict(strict_signed_json_object(path.read_bytes(), "source manifest"))
    except (OSError, ValueError) as error:
        return {"valid": False, "failures": [str(error)]}
    if manifest.get("schema") != "korpus.source-manifest.v2" or manifest.get("kind") != "source":
        return {"valid": False, "failures": ["invalid source manifest schema"]}
    records = manifest.get("files")
    if not isinstance(records, list):
        return {"valid": False, "failures": ["invalid source manifest records"]}
    failures = _structure_failures(manifest, records)
    if failures:
        return {"valid": False, "failures": failures}
    by_path = {record["path"]: record for record in records}
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
