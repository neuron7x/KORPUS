#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "apps/api/src")]
from korpus.application.provenance import compute_source_digest
from manifest_lib.integrity import mode_string
from manifest_lib.source_verification import source_manifest_failures
from manifest_paths import source_paths
from path_admission import regular_file
from release_identity import release_tag


def verify(root: Path) -> dict[str, object]:
    inventory = {
        path.as_posix(): mode_string(root / path, source=True) if regular_file(root / path) else ""
        for path in source_paths(root)
    }
    failures, digest = source_manifest_failures(root, inventory)
    return {
        "valid": not failures,
        "files": len(inventory),
        "root_sha256": digest,
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
