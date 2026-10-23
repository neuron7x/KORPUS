#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "apps/api/src")]
from korpus.application.provenance import DIGEST_SCOPE, compute_source_digest
from release_identity import release_tag
from source_manifest_contract import verify_source_manifest


def verify(root: Path) -> dict[str, object]:
    payload: dict[str, object] = verify_source_manifest(root)
    return payload


def bound_report(root: Path) -> dict[str, object]:
    payload = verify(root)
    payload["schema"] = "korpus.source-manifest-verification.v1"
    payload["status"] = "PASS" if payload["valid"] else "FAIL"
    payload["release"] = release_tag(root)
    payload["source_tree_sha256"] = compute_source_digest(root)
    payload["digest_scope"] = DIGEST_SCOPE
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
