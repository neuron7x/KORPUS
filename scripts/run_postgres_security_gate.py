#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

STATIC_TARGETS = [
    "apps/api/tests/test_postgres_role_grants.py",
    "apps/api/tests/test_postgres_role_hardening.py",
    "apps/api/tests/test_rls_identity_binder_contract.py",
    "apps/api/tests/test_postgres_security_gate_contract.py",
]
RUNTIME_TARGETS = [
    "apps/api/tests/test_postgres_role_grants.py",
    "apps/api/tests/test_repository_access_refusals.py",
    "apps/api/tests/test_tenancy_threats.py",
    "apps/api/tests/test_concurrent_audit.py",
    "apps/api/tests/test_postgres_rls_identity_boundary.py",
    "apps/api/tests/test_postgres_rls_identity_dml.py",
    "apps/api/tests/test_postgres_rls_binding_lifecycle.py",
    "apps/api/tests/test_postgres_role_reprovision_boundary.py",
]


def main() -> int:
    static = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--disable-warnings", *STATIC_TARGETS],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "apps/api/src")},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    external_url = bool(os.getenv("KORPUS_TEST_DATABASE_URL"))
    docker = shutil.which("docker") is not None
    runtime_exit: int | None = None
    runtime_tail = ""
    if external_url or docker:
        completed = subprocess.run(
            ["bash", "scripts/run_postgres_suite.sh", *RUNTIME_TARGETS],
            cwd=ROOT,
            env={**os.environ, "PYTHON": sys.executable},
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        runtime_exit = completed.returncode
        runtime_tail = (completed.stdout + completed.stderr)[-8000:]
    checks = {
        "security_contract_static": static.returncode == 0,
        "postgres_runtime_available": external_url or docker,
        "postgres_adversarial_suite": runtime_exit == 0,
    }
    failures = [name for name, ok in checks.items() if not ok]
    result = gate_payload(
        "postgres_security",
        status="PASS" if not failures else "FAIL",
        source_digest=compute_source_digest(ROOT),
        release=release_tag(),
        checks=checks,
        failures=failures,
        backend="postgresql" if runtime_exit == 0 else "UNEXECUTED",
        evidence_class="REAL_POSTGRESQL_REQUIRED",
        scope="LEGACY_POSTGRES_PLUS_NONFORGEABLE_RLS",
        static_pytest_targets=STATIC_TARGETS,
        pytest_targets=RUNTIME_TARGETS,
        runtime_exit_code=runtime_exit,
        runtime_tail=runtime_tail,
        static_tail=(static.stdout + static.stderr)[-4000:],
    )
    out = ROOT / "var/production/postgres_security-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
