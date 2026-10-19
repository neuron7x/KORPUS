#!/usr/bin/env python3
"""Reject packaging when checkout files differ from the exact Git source tree.

A source integrity PASS is not production authorization.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/api/src")]

from korpus.application.release_claim_tree import tracked_tree_digest  # noqa: E402


def main() -> int:
    digest = tracked_tree_digest(ROOT)
    result = {
        "schema": "korpus.clean-source-admission.v1",
        "status": "PASS" if digest is not None else "FAIL",
        "digest_scope": "tracked_tree_with_mode",
        "tracked_tree_sha256": digest,
        "production_authorized": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if digest is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
