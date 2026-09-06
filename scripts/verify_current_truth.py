#!/usr/bin/env python3
"""Fail if artifacts labelled current describe another source/release identity."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]
from current_truth_admission import (  # noqa: E402
    blocker_state_checks,
    claim_admission_checks,
    clean_room_checks,
    owner_packet_checks,
)
from current_truth_aliases import alias_checks  # noqa: E402
from current_truth_contract import final_truth_checks, report_binding_checks  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402


def evaluate(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    digest, release = compute_source_digest(root), release_tag(root)
    checks = {
        **report_binding_checks(root, release, digest),
        **final_truth_checks(root, release, digest),
        **claim_admission_checks(root, release, digest),
        **blocker_state_checks(root, release, digest),
        **owner_packet_checks(root, release, digest),
        # Репродукція з віддаленого джерела: доти артефакт лежав у reports/ і не
        # впливав ні на що. Доказ без споживача не є доказом — він є документом.
        **clean_room_checks(root, digest),
        **alias_checks(root, release),
    }
    failures = sorted(key for key, ok in checks.items() if not ok)
    return {
        "schema": "korpus.current-truth-verification.v2",
        "status": "PASS" if not failures else "FAIL",
        "release": release,
        "source_tree_sha256": digest,
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    payload = evaluate(root)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = args.out if args.out.is_absolute() else root / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
