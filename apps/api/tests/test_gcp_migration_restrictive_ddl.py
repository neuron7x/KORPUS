"""N-1 compatibility: forbid constraints on existing tables, preserve new-table DDL."""

from __future__ import annotations

import hashlib
import json
import os
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
            "op.create_table('accounts', sa.Column('id', sa.Integer()), "
            "if_not_exists=True)\n"
            "op.execute('ALTER TABLE accounts DROP COLUMN legacy')",
            "FAIL",
        ),
        (
            "op.create_table('accounts', sa.Column('id', sa.Integer()), "
            "if_not_exists=True)\n"
            "op.create_unique_constraint('uq', 'accounts', ['legacy'])",
            "FAIL",
        ),
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
            "op.create_table('parents', sa.Column('id', sa.Integer, primary_key=True))\n"
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
                    "drop_table",
                    "drop_column",
                    "drop_constraint",
                    "drop_index",
                    "rename_table",
                    "alter_column",
                    "execute",
                ],
            }
        ),
        encoding="utf-8",
    )
    report = evaluate(tmp_path)
    assert report["status"] == expected, report


@pytest.mark.parametrize(
    ("column_kwargs", "expected"),
    [
        ("nullable=True, unique=True", "FAIL"),
        ("nullable=True, index=True, unique=True", "FAIL"),
        ("nullable=True, index=True, unique=True, server_default='x'", "FAIL"),
        ("nullable=True, index=True, unique=False", "PASS"),
        ("nullable=True, index=True, unique=False, server_default='x'", "PASS"),
        ("nullable=True, unique=1", "FAIL"),
        ("nullable=True, unique=bool(1)", "FAIL"),
        ("nullable=True, unique=None", "PASS"),
    ],
)
def test_inline_unique_add_column_requires_n_minus_one_write_proof(
    tmp_path: Path, column_kwargs: str, expected: str
) -> None:
    body = f"op.add_column('accounts', sa.Column('fresh', sa.String(20), {column_kwargs}))"
    test_future_constraint_admission(tmp_path, body, expected)


def test_inline_unique_on_new_table_remains_expand_safe(tmp_path: Path) -> None:
    body = (
        "op.create_table('fresh', sa.Column('id', sa.Integer()))\n"
        "op.add_column('fresh', sa.Column('tag', sa.String(20), unique=True))"
    )
    test_future_constraint_admission(tmp_path, body, "PASS")


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


@pytest.mark.parametrize(
    ("table", "operation", "expected"),
    [
        ("Accounts", "op.execute('ALTER TABLE accounts DROP COLUMN existing')", "FAIL"),
        (
            "Accounts",
            "op.create_unique_constraint('uq', 'accounts', ['existing'])",
            "FAIL",
        ),
        ("accounts", "op.execute('ALTER TABLE accounts DROP COLUMN existing')", "PASS"),
        ("accounts", "op.create_unique_constraint('uq', 'accounts', ['id'])", "PASS"),
        (
            "Accounts",
            "op.execute('ALTER TABLE \"Accounts\" DROP COLUMN existing')",
            "PASS",
        ),
        ("Accounts", "op.create_unique_constraint('uq', 'Accounts', ['id'])", "PASS"),
    ],
)
def test_future_pg_case_sensitive_table_identity(
    tmp_path: Path, table: str, operation: str, expected: str
) -> None:
    """A quoted PG identifier must not justify DDL against a different table."""
    body = (
        f"op.create_table({table!r}, sa.Column('id', sa.Integer()), "
        "sa.Column('existing', sa.Integer()))\n"
        f"{operation}"
    )
    test_future_constraint_admission(tmp_path, body, expected)


@pytest.mark.parametrize(
    "operation",
    [
        "op.execute('ALTER TABLE accounts DROP COLUMN legacy')",
        "op.create_unique_constraint('uq', 'accounts', ['legacy'])",
    ],
)
def test_early_return_in_helper_does_not_prove_table_creation(
    tmp_path: Path, operation: str
) -> None:
    body = (
        "def install():\n"
        "    if True:\n"
        "        return\n"
        "    op.create_table('accounts', sa.Column('id', sa.Integer()))\n"
        "install()\n"
        f"{operation}"
    )
    test_future_constraint_admission(tmp_path, body, "FAIL")


def test_unconditional_helper_creation_remains_admitted(tmp_path: Path) -> None:
    body = (
        "def install():\n"
        "    op.create_table('accounts', sa.Column('id', sa.Integer()))\n"
        "install()\n"
        "op.execute('ALTER TABLE accounts DROP COLUMN legacy')"
    )
    test_future_constraint_admission(tmp_path, body, "PASS")


@pytest.mark.parametrize(
    ("column_type", "pg_type", "condition", "expected"),
    [
        ("sa.String(8)", "VARCHAR(8)", "fresh > 0", "FAIL"),
        ("sa.Boolean()", "BOOLEAN", "fresh > 0", "FAIL"),
        ("sa.Integer()", "INTEGER", "fresh > 0", "PASS"),
        ("sa.String(8)", "VARCHAR(8)", "fresh IS NULL", "PASS"),
    ],
)
def test_inline_check_type_oracle_on_real_postgres(
    tmp_path: Path, column_type: str, pg_type: str, condition: str, expected: str
) -> None:
    """Source admission and real PostgreSQL CHECK semantics must agree."""
    if admin_url := os.getenv("KORPUS_TEST_DATABASE_ADMIN_URL"):
        engine = sa.create_engine(admin_url, future=True)
        try:
            with engine.begin() as connection:
                version = int(connection.exec_driver_sql("SHOW server_version_num").scalar_one())
                assert 170000 <= version < 180000, version
                connection.exec_driver_sql("CREATE TEMP TABLE check_type_probe (id INTEGER)")
                connection.exec_driver_sql("INSERT INTO check_type_probe VALUES (1), (2)")
                statement = (
                    f"ALTER TABLE check_type_probe ADD COLUMN fresh {pg_type} CHECK ({condition})"
                )
                if expected == "PASS":
                    connection.exec_driver_sql(statement)
                    assert (
                        connection.exec_driver_sql(
                            "SELECT count(*) FROM check_type_probe WHERE fresh IS NULL"
                        ).scalar_one()
                        == 2
                    )
                else:
                    with (
                        pytest.raises(sa.exc.DBAPIError) as captured,
                        connection.begin_nested(),
                    ):
                        connection.exec_driver_sql(statement)
                    sqlstate = getattr(captured.value.orig, "sqlstate", None)
                    assert sqlstate == "42883", sqlstate
                    print(f"PG17 CHECK type refusal: {pg_type}, SQLSTATE={sqlstate}")
        finally:
            engine.dispose()
    body = (
        "op.add_column('accounts', sa.Column('fresh', "
        f"{column_type}, sa.CheckConstraint({condition!r})))"
    )
    test_future_constraint_admission(tmp_path, body, expected)
