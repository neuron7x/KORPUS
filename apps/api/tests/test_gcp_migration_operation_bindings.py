"""Trusted Alembic operation names still require bounded argument effects."""

import json
from pathlib import Path

import pytest

from apps.api.tests.test_gcp_migration_compatibility import _copy_surface, _future
from scripts.gcp.validate_migration_compatibility import evaluate


@pytest.mark.parametrize(
    "body",
    [
        "op.create_index('ix', 'existing', [sa.text('id); UPDATE existing SET id=99; --')])",
        "op.create_index('ix', 'existing', ['id'], postgresql_where=sa.text('unknown_effect()'))",
        "op.create_index('ix', 'existing', ['id'], postgresql_using='unknown')",
        "op.create_index('ix', 'existing', ['id'], columns=['other'])",
        "op.create_index('ix', 'existing', columns)",
        "op.create_index('ix', dynamic_table, ['id'])",
        "op.create_index('ix', 'existing', [])",
        "op.create_index('ix', 'existing', [sa.column('id')])",
        "op.create_index('ix', 'existing', ['id'], unknown=True)",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.create_index('ix', 'fresh', [sa.text('id')], unique=True)",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.create_unique_constraint('uq', 'fresh', [sa.text('unknown')])",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.create_unique_constraint('uq', 'fresh', ['id'], unknown=True)",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.create_check_constraint('ck', 'fresh', '1=1', unknown=True)",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.create_foreign_key('fk', 'fresh', 'fresh', [sa.text('id')], ['id'])",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.create_foreign_key('fk', 'fresh', 'fresh', ['id'], ['id'], unknown=True)",
        "op.add_column('existing', sa.Column('x', sa.Integer()), unknown=True)",
        "op.add_column(dynamic_table, sa.Column('x', sa.Integer()))",
        "op.add_column('existing', sa.Column('x', sa.Integer()), schema=7)",
        "op.get_bind(unknown=True)",
        "op.add_column('existing', sa.Column('x', sa.Integer(), nullable=1, server_default='0'))",
        "op.add_column('existing', sa.Column('x', sa.Integer(), primary_key=1, nullable=True))",
        "op.add_column('existing', sa.Column('x', sa.Integer(), index='unknown'))",
        "op.add_column('existing', sa.Column('x', sa.Integer(), autoincrement=sa.text('unknown')))",
        "op.add_column('existing', sa.Column('x', sa.Integer(), comment=sa.text('unknown')))",
        "op.add_column('existing', sa.Column('x', sa.Integer(), sa.CheckConstraint('1=1', unknown=True)))",
        "op.create_table('fresh', sa.Column('id', sa.Integer()), sa.UniqueConstraint('id', unknown=True))",
        "op.create_table('fresh', sa.Column('id', sa.Integer()), sa.ForeignKeyConstraint(['id'], ['fresh.id'], unknown=True))",
        "op.create_table('fresh', sa.Column('id', sa.Integer(), sa.ForeignKey('fresh.id', unknown=True)))",
        "op.bulk_insert(sa.table('existing', sa.column('id')), [{'id': 1}])",
        "if branch:\n    op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.bulk_insert(sa.table('fresh', sa.column('id')), [{'id': 1}])",
        "op.bulk_insert(sa.table('fresh', sa.column('id')), [{'id': 1}])\n"
        "op.create_table('fresh', sa.Column('id', sa.Integer()))",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.bulk_insert(sa.table('fresh', sa.column('id')), rows)",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.bulk_insert(sa.table('fresh', sa.column('id')), [{'id': sa.text('unknown')}])",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.bulk_insert(sa.table('fresh', sa.column('id')), [{'other': 1}])",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.bulk_insert(sa.table('fresh', sa.column('id')), [{'id': 1}], unknown=True)",
        "op.create_table('fresh', sa.Column('id', sa.Integer()), if_not_exists='unknown')",
    ],
)
def test_unknown_operation_bindings_are_denied(tmp_path: Path, body: str) -> None:
    root = _copy_surface(tmp_path)
    _future(root, body)
    report = evaluate(root)
    assert report["status"] == "FAIL", report


@pytest.mark.parametrize(
    "body",
    [
        "op.create_index('ix', 'existing', ['id'])",
        "op.create_index(index_name='ix', table_name='existing', columns=('id',), unique=False)",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.create_index('ix', 'fresh', ['id'], unique=True)",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.create_unique_constraint(constraint_name='uq', table_name='fresh', columns=['id'])",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.create_check_constraint(constraint_name='ck', table_name='fresh', condition='id > 0')",
        "op.create_table('fresh', sa.Column('id', sa.Integer(), primary_key=True))\n"
        "op.create_foreign_key('fk', 'fresh', 'fresh', ['id'], ['id'])",
        "op.add_column(table_name='existing', column=sa.Column('x', sa.Integer()), schema='public')",
        "op.get_bind()",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.bulk_insert(sa.table('fresh', sa.column('id')), [{'id': 1}], multiinsert=False)",
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.bulk_insert(table=sa.table('fresh', sa.column('id')), rows=[{'id': 1}])",
    ],
)
def test_supported_operation_bindings_remain_admitted(tmp_path: Path, body: str) -> None:
    root = _copy_surface(tmp_path)
    _future(root, body)
    report = evaluate(root)
    assert report["status"] == "PASS", report


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("op.execute('DROP TABLE existing')", "FAIL"),
        ("op.execute('CREATE TABLE fresh(id integer)')", "PASS"),
    ],
)
def test_execute_proof_cannot_be_disabled_by_policy(
    tmp_path: Path, body: str, expected: str
) -> None:
    root = _copy_surface(tmp_path)
    policy = root / "config/production/migration-policy.json"
    data = json.loads(policy.read_text())
    data["future_upgrade_forbidden_calls"].remove("execute")
    policy.write_text(json.dumps(data))
    _future(root, body)
    report = evaluate(root)
    assert report["status"] == expected, report
