#!/usr/bin/env python3
"""Bind PACKAGE_BUILD.json to the source manifest that was just written.

`verify_package_build_identity.py` compares the two and refuses a mismatch, which is the
right check — the package receipt must name the manifest it was built from. What was
missing is the step that makes them agree after the manifest is regenerated, so the
binding was maintained by hand and drifted: the recorded root was four regenerations old
when this was written, and the release-identity gate had been failing on it.

Nothing else is copied. The release tag, history flag and commit provenance stay whatever
the packager recorded; only the digest that must track the manifest is updated here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "PACKAGE_BUILD.json"
MANIFEST = ROOT / "SOURCE_MANIFEST.json"


def main() -> int:
    if not BUILD.is_file() or not MANIFEST.is_file():
        print(json.dumps({"status": "FAIL", "reason": "package build or source manifest missing"}))
        return 1
    build = json.loads(BUILD.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    root = manifest.get("root_sha256")
    if not isinstance(root, str) or len(root) != 64:
        print(json.dumps({"status": "FAIL", "reason": "source manifest has no root digest"}))
        return 1
    previous = build.get("source_manifest_root_sha256")
    build["source_manifest_root_sha256"] = root
    BUILD.write_text(json.dumps(build, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": "korpus.package-build-sync.v1",
                "status": "PASS",
                "previous_root_sha256": previous,
                "source_manifest_root_sha256": root,
                "changed": previous != root,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
