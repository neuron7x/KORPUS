"""Column constraints need the same table identity and a safe populated value."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.tests.test_gcp_migration_compatibility import _copy_surface, _future
from scripts.gcp.validate_migration_compatibility import evaluate


@pytest.mark.parametrize(
    "operation",
    [
        "op.add_column('fresh', sa.Column('x', sa.Integer(), unique=True), schema='other')",
        "op.add_column('fresh', sa.Column('x', sa.Integer(), unique=True), **{'schema': 'other'})",
        "op.add_column(table_name='fresh', column=sa.Column('x', sa.Integer(), "
        "unique=True), schema='other')",
    ],
)
def test_inline_unique_never_reuses_another_schema_creation(tmp_path: Path, operation: str) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "op.create_table('fresh', sa.Column('id', sa.Integer()))\n" + operation)
    report = evaluate(root)
    assert report["status"] == "FAIL", report
    assert any("schema" in reason for reason in report["findings"]), report


@pytest.mark.parametrize(
    "body",
    [
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.add_column('fresh', sa.Column('x', sa.Integer(), unique=True))",
        "op.add_column('accounts', sa.Column('x', sa.Integer(), nullable=True), schema='other')",
        "op.create_table('parents', sa.Column('id', sa.Integer(), primary_key=True))\n"
        "op.create_table('accounts', sa.Column('id', sa.Integer()))\n"
        "op.add_column('accounts', sa.Column('parent_id', sa.Integer(), "
        "sa.ForeignKey('parents.id'), nullable=True))",
        "op.create_table('parents', sa.Column('id', sa.Integer(), primary_key=True))\n"
        "op.create_table('accounts', sa.Column('id', sa.Integer()))\n"
        "op.add_column('accounts', sa.Column('parent_id', sa.Integer(), "
        "sa.ForeignKey('parents.id'), nullable=True, server_default=None))",
        "op.create_table('parents', sa.Column('id', sa.Integer(), primary_key=True))\n"
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.add_column('fresh', sa.Column('parent_id', sa.Integer(), "
        "sa.ForeignKey('parents.id'), server_default='0'))",
    ],
)
def test_column_identity_proof_preserves_safe_additions(tmp_path: Path, body: str) -> None:
    root = _copy_surface(tmp_path)
    _future(root, body)
    report = evaluate(root)
    assert report["status"] == "PASS", report


@pytest.mark.parametrize(
    "body",
    [
        "op.add_column('accounts', sa.Column('parent_id', sa.Integer(), "
        "sa.ForeignKey('parents.id'), server_default='0'))",
        "op.add_column('accounts', sa.Column('parent_id', sa.Integer(), "
        "sa.ForeignKey('parents.id'), **{'server_default': '0'}))",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.add_column('fresh', sa.Column('parent_id', sa.Integer(), "
        "sa.ForeignKey('parents.id'), server_default='0'), schema='other')",
    ],
)
def test_inline_foreign_key_default_needs_new_table_proof(tmp_path: Path, body: str) -> None:
    root = _copy_surface(tmp_path)
    _future(root, body)
    report = evaluate(root)
    assert report["status"] == "FAIL", report
    assert any("FOREIGN KEY" in reason for reason in report["findings"]), report


@pytest.mark.parametrize(
    "body",
    [
        "op.__dict__['execute'] = 'DIAGNOSTIC_LITERAL_CANARY'",
        "sa.__setattr__('Column', 'DIAGNOSTIC_LITERAL_CANARY')",
        "alias = op\nalias.execute('DIAGNOSTIC_LITERAL_CANARY')",
    ],
)
def test_namespace_diagnostics_do_not_disclose_literal_values(tmp_path: Path, body: str) -> None:
    root = _copy_surface(tmp_path)
    _future(root, body)
    report = evaluate(root)
    assert report["status"] == "FAIL", report
    assert any("trusted namespace" in reason for reason in report["findings"]), report
    assert "DIAGNOSTIC_LITERAL_CANARY" not in str(report)
