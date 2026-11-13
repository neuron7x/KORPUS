"""Future migration admission must inspect positional and named Column types."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.gcp.validate_migration_compatibility import evaluate


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("sa.Column('score', type_=sa.Integer(), nullable=False, server_default='oops')", "FAIL"),
        ("sa.Column('score', type_=sa.Integer(), nullable=False, server_default='123')", "PASS"),
        ("sa.Column('score', type_=sa.Integer(), nullable=True, server_default='oops')", "FAIL"),
        ("sa.Column('score', type_=sa.Integer(), nullable=True)", "PASS"),
        (
            "sa.Column('score', **{'type_': sa.Integer(), 'server_default': 'oops'})",
            "FAIL",
        ),
        (
            "sa.Column('score', **{'type_': sa.Integer(), 'server_default': '123'})",
            "PASS",
        ),
        ("sa.Column('score', sa.Integer(), nullable=False, server_default='oops')", "FAIL"),
        ("sa.Column('score', sa.Integer(), nullable=False, server_default='123')", "PASS"),
        (
            "sa.Column('score', sa.Integer(), type_=sa.Integer(), server_default='123')",
            "FAIL",
        ),
        ("sa.Column('score', server_default='123')", "FAIL"),
        (
            "sa.Column('score', sa.Integer(), nullable=False, server_default='2147483647')",
            "PASS",
        ),
        (
            "sa.Column('score', sa.Integer(), nullable=False, server_default='2147483648')",
            "FAIL",
        ),
        (
            "sa.Column('score', sa.Integer(), nullable=False, server_default='-2147483648')",
            "PASS",
        ),
        (
            "sa.Column('score', sa.Integer(), nullable=False, server_default='-2147483649')",
            "FAIL",
        ),
        (
            "sa.Column('score', sa.BigInteger(), nullable=False, server_default='9223372036854775807')",
            "PASS",
        ),
        (
            "sa.Column('score', sa.BigInteger(), nullable=False, server_default='9223372036854775808')",
            "FAIL",
        ),
        (
            "sa.Column('score', sa.BigInteger(), nullable=False, server_default='-9223372036854775808')",
            "PASS",
        ),
        (
            "sa.Column('score', sa.BigInteger(), nullable=False, server_default='-9223372036854775809')",
            "FAIL",
        ),
        (
            "sa.Column('score', sa.SmallInteger(), nullable=False, server_default='32767')",
            "PASS",
        ),
        (
            "sa.Column('score', sa.SmallInteger(), nullable=False, server_default='32768')",
            "FAIL",
        ),
        (
            "sa.Column('score', type_=sa.Integer(), nullable=False, server_default='2147483648')",
            "FAIL",
        ),
        ("sa.Column('note', sa.Text(), server_default='\\x00')", "FAIL"),
        ("sa.Column('note', sa.Text(), server_default='a\\x00b')", "FAIL"),
        ("sa.Column('note', sa.Text(), server_default='end\\x00')", "FAIL"),
        ("sa.Column('note', sa.Text(), server_default='plain')", "PASS"),
        ("sa.Column('note', sa.Text(), server_default='first\\nsecond')", "PASS"),
    ],
)
def test_literal_numeric_type_proof_includes_type_keyword(
    tmp_path: Path, column: str, expected: str
) -> None:
    versions = tmp_path / "apps/api/migrations/versions"
    versions.mkdir(parents=True)
    baseline = versions / "0001_base.py"
    baseline.write_text("revision='base'\ndown_revision=None\ndef upgrade():\n    pass\n")
    policy = tmp_path / "config/production/migration-policy.json"
    policy.parent.mkdir(parents=True)
    baseline_digest = hashlib.sha256(baseline.read_bytes()).hexdigest()
    policy.write_text(
        json.dumps(
            {
                "baseline_revision": "base",
                "baseline_files": {str(baseline.relative_to(tmp_path)): baseline_digest},
                "future_upgrade_forbidden_calls": [
                    "drop_table",
                    "drop_column",
                    "alter_column",
                    "execute",
                ],
            }
        )
    )
    (versions / "0002_future.py").write_text(
        "from alembic import op\nimport sqlalchemy as sa\n"
        "revision='future'\ndown_revision='base'\n"
        "def upgrade():\n    op.add_column('accounts', " + column + ")\n"
    )
    report = evaluate(tmp_path)
    assert report["status"] == expected, (column, report)
