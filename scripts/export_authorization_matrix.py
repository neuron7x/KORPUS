#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.policy import (  # noqa: E402
    KNOWN_PERMISSIONS,
    ROLE_PERMISSIONS,
    AuthorizationError,
    PolicyEngine,
)
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.domain.models import Identity  # noqa: E402
from release_identity import release_tag  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402


def _identity(role: str) -> Identity:
    return Identity(subject=f"matrix:{role}", roles=frozenset({role}), corpora=frozenset({"public"}))


def main() -> int:
    engine = PolicyEngine()
    matrix: dict[str, dict[str, bool]] = {}
    for role in sorted(ROLE_PERMISSIONS):
        row: dict[str, bool] = {}
        for permission in sorted(KNOWN_PERMISSIONS):
            try:
                engine.require(_identity(role), permission)
                row[permission] = True
            except AuthorizationError:
                row[permission] = False
        matrix[role] = row

    unknown_denied: dict[str, bool] = {}
    for role in sorted(ROLE_PERMISSIONS):
        try:
            engine.require(_identity(role), "__unknown__:permission")
            unknown_denied[role] = False
        except AuthorizationError:
            unknown_denied[role] = True

    expected = {
        role: {
            permission: "*" in grants or permission in grants
            for permission in sorted(KNOWN_PERMISSIONS)
        }
        for role, grants in ROLE_PERMISSIONS.items()
    }
    checks = {
        "matrix_matches_role_contract": matrix == expected,
        "unknown_permissions_fail_closed": all(unknown_denied.values()),
        "admin_is_not_vocabulary_bypass": unknown_denied.get("admin") is True,
    }
    failures = [name for name, ok in checks.items() if not ok]
    result = gate_payload(
        "authorization", status="PASS" if not failures else "FAIL",
        source_digest=compute_source_digest(ROOT), release=release_tag(), checks=checks,
        failures=failures, matrix=matrix, unknown_permission_denied=unknown_denied,
        evidence_class="EXECUTABLE_MATRIX",
    )
    out = ROOT / "var/production/authorization-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
