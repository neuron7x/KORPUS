#!/usr/bin/env python3
"""Governed, atomic promotion of a content-addressed PEC controller profile."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.controller_profile import ControllerProfile
from korpus.application.pec_promotion import (
    REQUIRED_RECEIPTS,
    promotion_binding_errors,
    promotion_errors,
)
from pec_common import receipt, sha256_file, write_json


def _named(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    name, raw = value.split("=", 1)
    if not name or not raw:
        raise argparse.ArgumentTypeError("expected non-empty NAME=PATH")
    return name, Path(raw)


def _load(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"receipt must be a JSON object: {path}")
    return raw


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--evidence", type=_named, action="append", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--change-id", required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "config/pec/promoted-controller.json")
    parser.add_argument("--receipt", type=Path, default=ROOT / "reports/PEC_PROMOTION_CURRENT.json")
    args = parser.parse_args()
    evidence = dict(args.evidence)
    profile = ControllerProfile.load(args.profile)
    raw_receipts = {name: _load(path) for name, path in sorted(evidence.items())}
    statuses = {name: str(raw.get("status", "UNKNOWN")) for name, raw in raw_receipts.items()}
    receipt_digests = {name: sha256_file(path) for name, path in sorted(evidence.items())}
    profile_file_digest = sha256_file(args.profile)
    errors = promotion_errors(profile, statuses)
    errors.extend(
        promotion_binding_errors(
            profile, raw_receipts, receipt_digests, profile_file_sha256=profile_file_digest
        )
    )
    errors = sorted(set(errors))
    status = "PASS" if not errors else "FAIL"
    if status == "PASS":
        _atomic_copy(args.profile, args.out)
        promoted_sha256 = sha256_file(args.out)
    else:
        promoted_sha256 = ""
    report = receipt(
        "pec_promotion",
        {
            "status": status,
            "profile_sha256": profile_file_digest,
            "profile_semantic_digest": profile.digest,
            "promoted_path": str(args.out.relative_to(ROOT)),
            "promoted_sha256": promoted_sha256,
            "approved_by": args.approved_by,
            "change_id": args.change_id,
            "required_receipts": list(REQUIRED_RECEIPTS),
            "receipt_statuses": statuses,
            "receipt_sha256": receipt_digests,
            "errors": errors,
        },
    )
    write_json(args.receipt, report)
    print(json.dumps(report, indent=2))
    return 0 if status == "PASS" else 1
