"""N-1 compatibility: forbid constraints on existing tables, preserve new-table DDL."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from scripts.gcp.validate_migration_compatibility import evaluate


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("op.create_index('idx', 'accounts', ['email'], unique=False)", "PASS"),
        ("op.create_index('idx', 'accounts', ['email'], unique=True)", "FAIL"),
        ("op.create_unique_constraint('uq', 'accounts', ['email'])", "FAIL"),
        ("op.create_check_constraint('ck', 'accounts', 'email IS NOT NULL')", "FAIL"),
        ("op.create_foreign_key('fk', 'accounts', 'parents', ['id'], ['id'])", "FAIL"),
        ("op.create_index('idx', 'accounts', ['email'], unique=bool(1))", "FAIL"),
        ("op.execute('DROP TABLE accounts')", "FAIL"),
        ("op.drop_table('accounts')", "FAIL"),
        (
            "op.create_table('fresh', sa.Column('id', sa.Integer, primary_key=True))\n"
            "op.create_index('ux', 'fresh', ['id'], unique=True)",
            "PASS",
        ),
        (
            "op.create_table('fresh', sa.Column('id', sa.Integer, primary_key=True))\n"
            "op.create_unique_constraint('uq', 'fresh', ['id'])",
            "PASS",
        ),
        (
            "op.create_table('fresh', sa.Column('id', sa.Integer, primary_key=True))\n"
            "op.create_check_constraint('ck', 'fresh', 'id > 0')",
            "PASS",
        ),
        (
            "op.create_table('fresh', sa.Column('id', sa.Integer, primary_key=True))\n"
            "op.create_foreign_key('fk', 'fresh', 'parents', ['id'], ['id'])",
            "PASS",
        ),
        (
            "if branch:\n    op.create_table('fresh', sa.Column('id', sa.Integer))\n"
            "op.create_unique_constraint('uq', 'fresh', ['id'])",
            "FAIL",
        ),
    ],
)
def test_future_constraint_admission(tmp_path: Path, body: str, expected: str) -> None:
    versions = tmp_path / "apps/api/migrations/versions"
    versions.mkdir(parents=True)
    base = b"revision = 'base'\ndown_revision = None\ndef upgrade():\n    pass\n"
    (versions / "0001_base.py").write_bytes(base)
    (versions / "0002_future.py").write_text(
        "from alembic import op\nimport sqlalchemy as sa\n"
        "revision = 'future'\ndown_revision = 'base'\ndef upgrade():\n"
        + "\n".join("    " + line for line in body.splitlines())
        + "\n",
        encoding="utf-8",
    )
    policy = tmp_path / "config/production/migration-policy.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps(
            {
                "baseline_revision": "base",
                "baseline_files": {
                    "apps/api/migrations/versions/0001_base.py": hashlib.sha256(base).hexdigest()
                },
                "future_upgrade_forbidden_calls": [
                    "drop_table", "drop_column", "drop_constraint", "drop_index",
                    "rename_table", "alter_column", "execute",
                ],
            }
        ),
        encoding="utf-8",
    )
    report = evaluate(tmp_path)
    assert report["status"] == expected, report


def test_real_alembic_unique_index_narrows_existing_writes() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE accounts (id INT PRIMARY KEY, email TEXT NOT NULL)")
        conn.exec_driver_sql("INSERT INTO accounts VALUES (1, 'same'), (2, 'same')")
        op = Operations(MigrationContext.configure(conn))
        with pytest.raises(sa.exc.IntegrityError):
            op.create_index("ux_existing_email", "accounts", ["email"], unique=True)
        op.create_index("ix_existing_email", "accounts", ["email"], unique=False)
        assert conn.exec_driver_sql("SELECT count(*) FROM accounts").scalar_one() == 2
