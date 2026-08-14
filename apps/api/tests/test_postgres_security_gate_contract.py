from __future__ import annotations

import inspect
from pathlib import Path

from scripts import run_postgres_security_gate as gate

REQUIRED_RLS_RUNTIME_TARGETS = {
    "apps/api/tests/test_postgres_rls_identity_boundary.py",
    "apps/api/tests/test_postgres_rls_identity_dml.py",
    "apps/api/tests/test_postgres_rls_binding_lifecycle.py",
    "apps/api/tests/test_postgres_role_reprovision_boundary.py",
}
REQUIRED_EXTERNAL_CREDENTIALS = {
    "KORPUS_TEST_DATABASE_URL",
    "KORPUS_TEST_DATABASE_ADMIN_URL",
    "KORPUS_REVIEW_DATABASE_URL",
    "RLS_IDENTITY_DATABASE_URL",
}


def test_production_postgres_gate_executes_nonforgeable_rls_destruction_suite() -> None:
    assert REQUIRED_RLS_RUNTIME_TARGETS <= set(gate.RUNTIME_TARGETS)


def test_gate_contract_is_itself_checked_before_runtime_promotion() -> None:
    assert "apps/api/tests/test_postgres_security_gate_contract.py" in gate.STATIC_TARGETS
    assert "apps/api/tests/test_postgres_role_hardening.py" in gate.STATIC_TARGETS
    assert "apps/api/tests/test_rls_identity_binder_contract.py" in gate.STATIC_TARGETS


def test_external_runtime_requires_complete_split_postgres_boundary() -> None:
    assert set(gate.EXTERNAL_REQUIRED) == REQUIRED_EXTERNAL_CREDENTIALS
    source = inspect.getsource(gate.main)
    assert "external_ready = all(os.getenv(name) for name in EXTERNAL_REQUIRED)" in source
    assert "runtime_available = external_ready if external_requested else docker_available" in source


def test_postgres_gate_cannot_promote_static_or_unexecuted_evidence() -> None:
    source = inspect.getsource(gate.main)
    assert '"postgres_runtime_available": runtime_available' in source
    assert '"postgres_adversarial_suite": runtime_exit == 0' in source
    assert 'backend="postgresql" if runtime_exit == 0 else "UNEXECUTED"' in source
    assert 'scope="LEGACY_POSTGRES_PLUS_NONFORGEABLE_RLS"' in source
    assert '"bash", "scripts/run_postgres_suite.sh", *RUNTIME_TARGETS' in source


def test_postgres_suite_honors_explicit_destruction_targets() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "scripts/run_postgres_suite.sh").read_text(encoding="utf-8")
    assert 'pytest_targets=("$@")' in source
    assert 'if (( ${#pytest_targets[@]} == 0 )); then' in source
    assert source.count('"${pytest_targets[@]}" --no-cov') == 2
    assert 'apps/api/tests --no-cov "$@"' not in source
