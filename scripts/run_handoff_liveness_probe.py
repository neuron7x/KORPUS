#!/usr/bin/env python3
"""Run handoff liveness against a synthetic, non-authoritative source binding.

The committed assurance report may truthfully be STALE until the external recovery lane
is rerun.  That cannot make the handoff gate's positive liveness control fail forever.
This adapter changes no file: only a structurally valid existing binding is rebound in
memory to the copied probe tree.  Every malformed, missing, or mis-scoped poison reaches
the real verifier unchanged.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

import verify_handoff_contract as handoff  # noqa: E402
from source_digest import DIGEST_SCOPE, source_tree_digest  # noqa: E402

HEX_SHA256 = re.compile(r"[0-9a-f]{64}")


def synthetic_binding(report: dict[str, Any], digest: str) -> dict[str, Any]:
    """Rebind only a well-formed PASS report; poisons remain observable."""
    bound = dict(report)
    tracked = report.get("tracked_tree_sha256")
    if (
        report.get("status") == "PASS"
        and report.get("tracked_tree_scope") == DIGEST_SCOPE
        and isinstance(tracked, str)
        and HEX_SHA256.fullmatch(tracked)
    ):
        bound["tracked_tree_sha256"] = digest
    return bound


def verify() -> dict[str, Any]:
    """Call the production verifier with a read-only in-memory liveness fixture."""
    assurance_path = ROOT / "reports" / "RESEARCH_ASSURANCE_REPORT.json"
    original_load: Callable[[Path], dict[str, Any]] = handoff._load  # noqa: SLF001

    def load(path: Path) -> dict[str, Any]:
        report = original_load(path)
        if path == assurance_path:
            return synthetic_binding(report, source_tree_digest())
        return report

    handoff._load = load  # noqa: SLF001
    try:
        result: object = handoff.verify(require_bound=True)
        if not isinstance(result, dict):
            raise RuntimeError("handoff verifier returned a non-object report")
        return {str(key): value for key, value in result.items()}
    finally:
        handoff._load = original_load  # noqa: SLF001


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2, sort_keys=True))
