from __future__ import annotations

import inspect

from scripts import run_postgres_security_gate as gate

REQUIRED_RLS_RUNTIME_TARGETS = {
    "apps/api/tests/test_postgres_rls_identity_boundary.py",
    "apps/api/tests/test_postgres_rls_identity_dml.py",
    "apps/api/tests/test_postgres_rls_binding_lifecycle.py",
    "apps/api/tests/test_postgres_role_reprovision_boundary.py",
}


def test_production_postgres_gate_executes_nonforgeable_rls_destruction_suite() -> None:
    assert REQUIRED_RLS_RUNTIME_TARGETS <= set(gate.RUNTIME_TARGETS)


def test_gate_contract_is_itself_checked_before_runtime_promotion() -> None:
    assert "apps/api/tests/test_postgres_security_gate_contract.py" in gate.STATIC_TARGETS
    assert "apps/api/tests/test_postgres_role_hardening.py" in gate.STATIC_TARGETS
    assert "apps/api/tests/test_rls_identity_binder_contract.py" in gate.STATIC_TARGETS


def test_postgres_gate_cannot_promote_static_or_unexecuted_evidence() -> None:
    source = inspect.getsource(gate.main)
    assert '"postgres_runtime_available": external_url or docker' in source
    assert '"postgres_adversarial_suite": runtime_exit == 0' in source
    assert 'backend="postgresql" if runtime_exit == 0 else "UNEXECUTED"' in source
    assert 'scope="LEGACY_POSTGRES_PLUS_NONFORGEABLE_RLS"' in source
    assert '"bash", "scripts/run_postgres_suite.sh", *RUNTIME_TARGETS' in source
