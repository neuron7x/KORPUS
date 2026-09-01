#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]
from korpus.application.production_assurance import gate_payload  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from postgres_gate_process import run as process_run  # noqa: E402
from postgres_gate_process import runtime as process_runtime  # noqa: E402
from release_identity import release_tag  # noqa: E402

#: Гейт зветься «postgres security», а міряв лише гранти й відмови репозиторію.
#: 01.09.2026 до дерева додано деструктивні контролі самої МЕЖІ — підробка claim'ів
#: RLS, стан політик, знищення дрейфу прав, походження затвердження — і жоден із них
#: сюди не потрапив би сам. Гейт, який називає властивість, якої не запускає, — це
#: твердження без виміру. `test_postgres_security_gate_contract.py` тримає цей
#: перелік проти мовчазного скорочення.
TARGETS = [
    "apps/api/tests/test_postgres_role_grants.py",
    "apps/api/tests/test_repository_access_refusals.py",
    "apps/api/tests/test_tenancy_threats.py",
    "apps/api/tests/test_audit.py",
    # Деструктивні контролі межі: кожен питає, що ПРОХОДИТЬ не маючи права.
    "apps/api/tests/test_postgres_rls_claim_forgery.py",
    "apps/api/tests/test_postgres_rls_policy_state.py",
    "apps/api/tests/test_postgres_role_reprovision_boundary.py",
    "apps/api/tests/test_postgres_approval_provenance.py",
    # Позитивний контроль: набір, у якому все відмовляє, доводить лише поломку.
    "apps/api/tests/test_postgres_integration.py",
]


def main() -> int:
    targets_present = all((ROOT / target).is_file() for target in TARGETS)
    static = process_run(
        ROOT,
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "--disable-warnings",
            TARGETS[0],
        ],
        120,
    )
    available, runtime_exit, runtime_tail = process_runtime(ROOT, TARGETS, targets_present)
    checks = {
        "target_files_present": targets_present,
        "grant_contract_static": static.returncode == 0,
        "postgres_runtime_available": available,
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
        pytest_targets=TARGETS,
        runtime_exit_code=runtime_exit,
        runtime_tail=runtime_tail,
        static_tail=(static.stdout + static.stderr)[-4000:],
    )
    out = ROOT / "var/production/postgres_security-gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
