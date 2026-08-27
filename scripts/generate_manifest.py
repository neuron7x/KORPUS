#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from manifest_lib.integrity import file_record, manifest_root
from manifest_paths import distribution_paths, source_paths


def _records(root: Path, paths: list[Path], *, source: bool) -> list[dict[str, object]]:
    return [file_record(root / relative, relative, source=source) for relative in paths]


def build_manifest(root: Path, *, kind: str = "source") -> dict[str, object]:
    if kind not in {"source", "distribution"}:
        raise ValueError(f"unknown manifest kind: {kind}")
    paths = source_paths(root) if kind == "source" else distribution_paths(root)
    records = _records(root, paths, source=kind == "source")
    root_digest = manifest_root(records)
    return {
        "schema": f"korpus.{kind}-manifest.v2",
        "kind": kind,
        "manifest_self_excluded": True,
        "file_count": len(records),
        "root_sha256": root_digest,
        "files": records,
    }


def write_manifest(root: Path, output: Path, *, kind: str) -> dict[str, object]:
    manifest = build_manifest(root, kind=kind)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--kind", choices=("source", "distribution"), default="source")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    default_name = "SOURCE_MANIFEST.json" if args.kind == "source" else "DISTRIBUTION_MANIFEST.json"
    output = args.output or (root / default_name)
    output = output if output.is_absolute() else root / output
    manifest = write_manifest(root, output, kind=args.kind)
    print(
        json.dumps(
            {
                "kind": args.kind,
                "file_count": manifest["file_count"],
                "root_sha256": manifest["root_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
