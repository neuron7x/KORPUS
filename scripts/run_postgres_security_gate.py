#!/usr/bin/env python3
from __future__ import annotations

import json, os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

TARGETS = [
    "apps/api/tests/test_postgres_role_grants.py",
    "apps/api/tests/test_repository_access_refusals.py",
    "apps/api/tests/test_tenancy_threats.py",
    "apps/api/tests/test_audit.py",
]


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "apps/api/src")},
                          capture_output=True, text=True, check=False, timeout=timeout)


def _runtime(targets_present: bool) -> tuple[bool, int | None, str]:
    available = bool(os.getenv("KORPUS_TEST_DATABASE_URL")) or shutil.which("docker") is not None
    if not targets_present or not available:
        return available, None, ""
    completed = _run(["bash", "scripts/run_postgres_suite.sh", *TARGETS], 600)
    return available, completed.returncode, (completed.stdout + completed.stderr)[-8000:]


def main() -> int:
    targets_present = all((ROOT / target).is_file() for target in TARGETS)
    static = _run([sys.executable, "-m", "pytest", "-q", "--disable-warnings", TARGETS[0]], 120)
    available, runtime_exit, runtime_tail = _runtime(targets_present)
    checks = {
        "target_files_present": targets_present,
        "grant_contract_static": static.returncode == 0,
        "postgres_runtime_available": available,
        "postgres_adversarial_suite": runtime_exit == 0,
    }
    failures = [name for name, ok in checks.items() if not ok]
    result = gate_payload(
        "postgres_security", status="PASS" if not failures else "FAIL", source_digest=compute_source_digest(ROOT),
        release=release_tag(), checks=checks, failures=failures, backend="postgresql" if runtime_exit == 0 else "UNEXECUTED",
        evidence_class="REAL_POSTGRESQL_REQUIRED", pytest_targets=TARGETS, runtime_exit_code=runtime_exit,
        runtime_tail=runtime_tail, static_tail=(static.stdout + static.stderr)[-4000:],
    )
    out = ROOT / "var/production/postgres_security-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
