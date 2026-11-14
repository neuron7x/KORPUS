"""Fail-closed argument binding for future Alembic add_column migrations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.gcp.validate_migration_compatibility import evaluate


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (
            "op.add_column(table_name='accounts', column=sa.Column('x', "
            "sa.Integer(), nullable=False))",
            "FAIL",
        ),
        (
            "op.add_column('accounts', column=sa.Column('x', sa.Integer(), nullable=False))",
            "FAIL",
        ),
        (
            "op.add_column(**{'table_name':'accounts','column':sa.Column('x', "
            "sa.Integer(), nullable=False)})",
            "FAIL",
        ),
        (
            "op.add_column('accounts', *[sa.Column('x', sa.Integer(), nullable=False)])",
            "FAIL",
        ),
        ("op.add_column(**kwargs)", "FAIL"),
        ("op.add_column('accounts', **kwargs)", "FAIL"),
        (
            "op.add_column('accounts', sa.Column('x', sa.Integer()), "
            "column=sa.Column('y', sa.Integer()))",
            "FAIL",
        ),
        (
            "op.add_column('accounts', table_name='accounts', column=sa.Column('x', sa.Integer()))",
            "FAIL",
        ),
        (
            "op.add_column('accounts', column=sa.Column('x', sa.Integer()), "
            "**{'column':sa.Column('y', sa.Integer())})",
            "FAIL",
        ),
        ("op.add_column(column=sa.Column('x', sa.Integer()))", "FAIL"),
        ("op.add_column(table_name='accounts')", "FAIL"),
        ("op.add_column(table_name='accounts', column=make_column())", "FAIL"),
        (
            "op.add_column(table_name='accounts', column=sa.Column('x', "
            "sa.Integer(), nullable=True))",
            "PASS",
        ),
        (
            "op.add_column('accounts', column=sa.Column('x', sa.Integer(), nullable=True))",
            "PASS",
        ),
        (
            "op.add_column(**{'table_name':'accounts','column':sa.Column('x', "
            "sa.Integer(), nullable=True)})",
            "PASS",
        ),
        (
            "op.add_column('accounts', sa.Column('x', sa.Integer(), nullable=False,"
            " server_default='1'))",
            "PASS",
        ),
        (
            "op.add_column(table_name='accounts', column=sa.Column('x', "
            "sa.Integer(), nullable=False, server_default='1'))",
            "PASS",
        ),
    ],
)
def test_admission_binds_literal_column_or_refuses_unknown(
    tmp_path: Path, operation: str, expected: str
) -> None:
    versions = tmp_path / "apps/api/migrations/versions"
    versions.mkdir(parents=True)
    baseline = versions / "0001_baseline.py"
    baseline.write_text("revision='base'\ndown_revision=None\ndef upgrade():\n    pass\n")
    policy = tmp_path / "config/production/migration-policy.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps(
            {
                "baseline_revision": "base",
                "baseline_files": {
                    str(baseline.relative_to(tmp_path)): hashlib.sha256(
                        baseline.read_bytes()
                    ).hexdigest()
                },
                "future_upgrade_forbidden_calls": [
                    "drop_table",
                    "drop_column",
                    "drop_constraint",
                    "drop_index",
                    "rename_table",
                    "alter_column",
                    "execute",
                ],
            }
        )
    )
    (versions / "0002_future.py").write_text(
        "from alembic import op\nimport sqlalchemy as sa\n"
        f"revision='future'\ndown_revision='base'\ndef upgrade():\n    {operation}\n"
    )
    report = evaluate(tmp_path)
    assert report["status"] == expected, (operation, report["findings"])
