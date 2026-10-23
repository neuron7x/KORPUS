#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "apps/api/src")]

from korpus.application.final_release_evidence import strict_signed_json_object  # noqa: E402
from package_identity_contract import BUILD_FIELDS, valid_release_identity  # noqa: E402
from path_admission import regular_file  # noqa: E402

HEX40, HEX64 = re.compile(r"^[0-9a-f]{40}$"), re.compile(r"^[0-9a-f]{64}$")


def _load(path: Path) -> dict[str, object]:
    if not regular_file(path):
        raise ValueError(f"{path.name} missing or symlinked")
    return dict(strict_signed_json_object(path.read_bytes(), path.name))


def verify(root: Path) -> list[str]:
    try:
        build = _load(root / "PACKAGE_BUILD.json")
        source = _load(root / "SOURCE_MANIFEST.json")
        release = _load(root / "apps/api/src/korpus/release.json")
    except (OSError, ValueError) as error:
        return [f"package/source identity JSON unreadable: {error}"]
    manifest_root, version, tag = source.get("root_sha256"), release.get("version"), release.get("tag")  # fmt: skip
    derived = build.get("derived_from_source_commit")
    valid_tag = isinstance(version, str) and bool(version) and tag == f"v{version}"  # fmt: skip
    valid_derived = derived is None or (isinstance(derived, str) and bool(HEX40.fullmatch(derived)))  # fmt: skip
    checks = {
        "package build fields mismatch": set(build) == BUILD_FIELDS,
        "package build schema mismatch": build.get("schema") == "korpus.package-build.v2",
        "release identity contract mismatch": valid_release_identity(release),
        "release identity tag/version mismatch": valid_tag,
        "package build release mismatch": build.get("release") == tag,
        "source manifest schema mismatch": source.get("schema") == "korpus.source-manifest.v2",
        "source manifest root is not a SHA-256 digest": isinstance(manifest_root, str)
        and bool(HEX64.fullmatch(manifest_root)),
        "package build source manifest root mismatch": build.get("source_manifest_root_sha256")
        == manifest_root,
        "clean-source package must exclude Git history": build.get("history_included") is False,
        "gitless canonical package must not invent a source commit": build.get("source_commit")
        is None,
        "gitless canonical package must state that import creates commit identity": build.get(
            "import_required_to_obtain_git_commit"
        )
        is True,
        "derived source commit must be null or a 40-char Git object id": valid_derived,
    }
    return [message for message, passed in checks.items() if not passed]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    root = parser.parse_args().root.absolute()
    failures = verify(root)
    try:
        release = _load(root / "apps/api/src/korpus/release.json").get("tag")
    except (OSError, ValueError):
        release = None
    payload = {"schema": "korpus.package-build-verification.v1", "status": "PASS" if not failures else "FAIL", "release": release, "failures": failures}  # fmt: skip
    print(json.dumps(payload, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
