"""New table names do not prove that existing tables keep their read/write contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.tests.test_gcp_migration_compatibility import _copy_surface, _future
from scripts.gcp.validate_migration_compatibility import evaluate


@pytest.mark.parametrize(
    "body",
    [
        "op.create_table('fresh', sa.Column('id', sa.Integer()), "
        "postgresql_partition_by='RANGE (id)')\n"
        "op.execute('ALTER TABLE fresh ATTACH PARTITION existing FOR VALUES FROM (0) TO (10)')",
        "op.create_table('fresh', sa.Column('payload', sa.Integer()), "
        "postgresql_inherits='existing')",
        "op.create_table('fresh', sa.Column('payload', sa.Integer()), "
        "**{'postgresql_inherits': 'existing'})",
        "op.execute('CREATE TABLE fresh(payload integer) INHERITS(existing)')",
        "op.execute('CREATE TABLE fresh(LIKE existing INCLUDING ALL)')",
        "op.execute('CREATE TABLE fresh(id integer REFERENCES existing(id))')",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.execute('ALTER TABLE fresh INHERIT existing')",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.execute('ALTER TABLE fresh DROP COLUMN id CASCADE')",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.execute('ALTER TABLE fresh ADD CHECK (mutate_existing(id))')",
        "op.create_table('fresh', sa.Column('id', sa.Integer(), sa.ForeignKey('existing.id')))",
        "op.create_table('fresh', sa.Column(sa.ForeignKey('existing.id'), "
        "name='id', type_=sa.Integer))",
        "op.create_table('fresh', sa.Column('id', sa.Integer()), "
        "sa.ForeignKeyConstraint(['id'], ['existing.id']))",
        "op.create_table('fresh', *[sa.Column('id', sa.Integer(), sa.ForeignKey('existing.id'))])",
        "op.create_table('fresh', sa.Column('id', sa.Integer(), "
        "server_default=sa.text(\"nextval('existing_sequence')\")))",
        "op.create_table('fresh', sa.Column('id', sa.Integer()), "
        "sa.CheckConstraint('mutate_existing(id)'))",
    ],
)
def test_new_table_nonlocal_effects_are_denied(tmp_path: Path, body: str) -> None:
    root = _copy_surface(tmp_path)
    _future(root, body)
    report = evaluate(root)
    assert report["status"] == "FAIL", report


@pytest.mark.parametrize(
    "body",
    [
        # These exact bodies formerly had PASS oracles. PG proves they can prevent
        # deletion of a pre-existing parent once the new child contains a reference.
        "op.create_table('fresh', sa.Column('id', sa.Integer, primary_key=True))\n"
        "op.create_foreign_key('fk', 'fresh', 'parents', ['id'], ['id'])",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.add_column('fresh', sa.Column('parent_id', sa.Integer(), "
        "sa.ForeignKey('parents.id'), server_default='0'))",
        "op.add_column('accounts', sa.Column('parent_id', sa.Integer(), "
        "sa.ForeignKey('parents.id'), nullable=True))",
        "op.add_column('accounts', sa.Column('parent_id', sa.Integer(), "
        "sa.ForeignKey('parents.id'), nullable=True, server_default=None))",
    ],
)
def test_previously_positive_foreign_key_oracles_are_nonlocal(tmp_path: Path, body: str) -> None:
    root = _copy_surface(tmp_path)
    _future(root, body)
    report = evaluate(root)
    assert report["status"] == "FAIL", report
    assert any("FOREIGN KEY" in reason for reason in report["findings"]), report


@pytest.mark.parametrize(
    "operation",
    [
        "op.create_foreign_key('fk', 'fresh', 'parents', ['id'], ['id'])",
        "op.create_foreign_key(constraint_name='fk', source_table='fresh', "
        "referent_table='parents', local_cols=['id'], remote_cols=['id'])",
        "op.add_column('fresh', sa.Column('parent_id', sa.Integer(), "
        "sa.ForeignKey('parents.id'), nullable=True))",
    ],
)
def test_foreign_keys_between_proven_new_tables_remain_local(
    tmp_path: Path, operation: str
) -> None:
    root = _copy_surface(tmp_path)
    _future(
        root,
        "op.create_table('parents', sa.Column('id', sa.Integer(), primary_key=True))\n"
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n" + operation,
    )
    report = evaluate(root)
    assert report["status"] == "PASS", report


@pytest.mark.parametrize(
    "constraint",
    [
        "sa.Column('parent_id', sa.Integer(), sa.ForeignKey('parents.id'))",
        "sa.ForeignKeyConstraint(['id'], ['parents.id'])",
        "sa.Column('parent_id', sa.Integer(), sa.ForeignKey('fresh.id'))",
    ],
)
def test_inline_foreign_keys_to_new_or_self_tables_remain_local(
    tmp_path: Path, constraint: str
) -> None:
    root = _copy_surface(tmp_path)
    _future(
        root,
        "op.create_table('parents', sa.Column('id', sa.Integer(), primary_key=True))\n"
        "op.create_table('fresh', sa.Column('id', sa.Integer(), primary_key=True), "
        + constraint
        + ")",
    )
    report = evaluate(root)
    assert report["status"] == "PASS", report


@pytest.mark.parametrize(
    "effect",
    [
        "ENABLE ROW LEVEL SECURITY",
        "DISABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "NO FORCE ROW LEVEL SECURITY",
        "DROP COLUMN id",
        "DROP COLUMN IF EXISTS id",
    ],
)
def test_explicit_local_alter_forms_remain_admitted(tmp_path: Path, effect: str) -> None:
    root = _copy_surface(tmp_path)
    _future(
        root,
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        f"op.execute('ALTER TABLE fresh {effect}')",
    )
    report = evaluate(root)
    assert report["status"] == "PASS", report


def test_raw_create_simple_literal_columns_remains_admitted(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "op.execute('CREATE TABLE fresh(id bigint PRIMARY KEY, note text)')")
    report = evaluate(root)
    assert report["status"] == "PASS", report
