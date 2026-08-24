#!/usr/bin/env python3
"""Verify clean-source package-build metadata against canonical source/release identity."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _release_tag(root: Path) -> str:
    path = root / "apps/api/src/korpus/release.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = str(payload.get("version", ""))
    tag = str(payload.get("tag", ""))
    if not version or tag != f"v{version}":
        raise ValueError("release identity tag/version mismatch")
    return tag


def verify(root: Path) -> list[str]:
    failures: list[str] = []
    build_path = root / "PACKAGE_BUILD.json"
    source_path = root / "SOURCE_MANIFEST.json"
    if not build_path.is_file():
        return ["PACKAGE_BUILD.json missing"]
    if not source_path.is_file():
        return ["SOURCE_MANIFEST.json missing"]
    try:
        build = json.loads(build_path.read_text(encoding="utf-8"))
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"package/source identity JSON unreadable: {error}"]
    if build.get("schema") != "korpus.package-build.v2":
        failures.append("package build schema mismatch")
    if build.get("release") != _release_tag(root):
        failures.append("package build release mismatch")
    manifest_root = source.get("root_sha256")
    if not isinstance(manifest_root, str) or not HEX64.fullmatch(manifest_root):
        failures.append("source manifest root is not a SHA-256 digest")
    if build.get("source_manifest_root_sha256") != manifest_root:
        failures.append("package build source manifest root mismatch")
    if build.get("history_included") is not False:
        failures.append("clean-source package must exclude Git history")
    if build.get("source_commit") is not None:
        failures.append("gitless canonical package must not invent a source commit")
    if build.get("import_required_to_obtain_git_commit") is not True:
        failures.append("gitless canonical package must state that import creates commit identity")
    derived = build.get("derived_from_source_commit")
    if derived is not None and (not isinstance(derived, str) or not HEX40.fullmatch(derived)):
        failures.append("derived source commit must be null or a 40-char Git object id")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    failures = verify(root)
    payload = {
        "schema": "korpus.package-build-verification.v1",
        "status": "PASS" if not failures else "FAIL",
        "release": _release_tag(root),
        "failures": failures,
    }
    print(json.dumps(payload, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
