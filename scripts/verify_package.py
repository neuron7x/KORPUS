#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from manifest_lib.integrity import archive_modes, archive_root, file_sha256, record_failures
from manifest_paths import (
    MANIFEST_NAME,
    RECEIPT_NAME,
    RECEIPT_SCHEMA,
    distribution_manifest_contract,
    expected_full_ssot_receipt,
    json_object,
)
from zip_safety import safety_failures


def _receipt_binding_failures(receipt: dict[str, object], expected: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if receipt.get("status") != "PASS":
        failures.append("full SSOT receipt status is not PASS")
    if receipt.get("failures") != []:
        failures.append("full SSOT receipt contains failures")
    if set(receipt) != set(expected):
        failures.append("full SSOT receipt fields are not exact")
    mismatched = sorted(key for key in expected if receipt.get(key) != expected[key])
    failures.append(f"full SSOT receipt binding mismatch: {mismatched}")
    return failures


ReceiptContext = tuple[
    Path,
    dict[str, object],
    dict[str, dict[str, object]],
    dict[str, str],
]


def _manifest_mode(zf: zipfile.ZipFile, root_name: str) -> str:
    expected = f"{root_name}/{MANIFEST_NAME}" if root_name else MANIFEST_NAME
    matches = [item for item in zf.infolist() if not item.is_dir() and item.filename == expected]
    if len(matches) != 1:
        return ""
    return f"0{((matches[0].external_attr >> 16) & 0o7777):o}"


def _verify_receipt(
    context: ReceiptContext,
    failures: list[str],
    required: bool,
) -> bool:
    root, manifest, records, modes = context
    path = root / RECEIPT_NAME
    receipt = json_object(path) if path.is_file() else None
    if receipt is None or receipt.get("schema") != RECEIPT_SCHEMA:
        if required:
            failures.append("exact full SSOT package receipt v4 is required")
        return False
    if RECEIPT_NAME in records:
        failures.append("full SSOT receipt must be excluded from distribution records")
    expected = expected_full_ssot_receipt(root, manifest)
    if expected is None:
        failures.append("full SSOT receipt source/release identity is invalid")
    elif receipt != expected:
        failures.extend(_receipt_binding_failures(receipt, expected))
    if modes.get(RECEIPT_NAME) != "0644":
        failures.append("full SSOT receipt mode must be 0644")
    return True


def _verify_tree(
    root: Path,
    records: dict[str, dict[str, object]],
    archive_modes: dict[str, str],
    *,
    receipt_excluded: bool,
) -> list[str]:
    failures = []
    excluded = {MANIFEST_NAME, RECEIPT_NAME} if receipt_excluded else {MANIFEST_NAME}
    actual = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.relative_to(root).as_posix() not in excluded
    )
    if sorted(records) != actual:
        # Name both directions: injected payload is archive-minus-manifest.
        failures.append(
            "path parity mismatch "
            f"in_manifest_not_in_archive={sorted(set(records) - set(actual))} "
            f"in_archive_not_in_manifest={sorted(set(actual) - set(records))}"
        )
    for relative in actual:
        record = records.get(relative)
        if record is None:
            continue  # named by the parity line above; an empty record reports path=None
        failures.extend(record_failures(root / relative, record, archive_modes.get(relative)))
    return failures


def verify(archive: Path, *, require_full_ssot: bool = False) -> tuple[list[str], int]:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="korpus-package-verify-") as tmp_name:
        tmp = Path(tmp_name)
        with zipfile.ZipFile(archive) as zf:
            safety = safety_failures(zf)
            if safety:
                return safety, 0
            zf.extractall(tmp)
            root = archive_root(tmp)
            root_name = root.name if root != tmp else ""
            modes = archive_modes(zf, root_name)
            modes[MANIFEST_NAME] = _manifest_mode(zf, root_name)
        manifest, records, contract_failures = distribution_manifest_contract(root)
        failures.extend(contract_failures)
        receipt_excluded = _verify_receipt(
            (root, manifest, records, modes),
            failures,
            require_full_ssot,
        )
        if modes.get(MANIFEST_NAME) != "0644":
            failures.append("distribution manifest mode must be 0644")
        failures.extend(_verify_tree(root, records, modes, receipt_excluded=receipt_excluded))
        return failures, len(records) + 1 + int(receipt_excluded)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-full-ssot", action="store_true")
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve()
    if not archive.is_file():
        raise SystemExit(f"archive missing: {archive}")
    try:
        failures, files = verify(archive, require_full_ssot=args.require_full_ssot)
    except (RuntimeError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        failures, files = [str(exc)], 0
    payload = {
        "valid": not failures,
        "verification_scope": "archive_integrity",
        "provenance_admitted": False,
        "archive": str(archive),
        "sha256": file_sha256(archive),
        "files": files,
    }
    if failures:
        payload["failures"] = failures
    print(json.dumps(payload, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
