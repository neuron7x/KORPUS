"""PostgreSQL literal defaults must fit the declared runtime storage type."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.tests.test_gcp_migration_compatibility import _copy_surface, _future
from scripts.gcp.validate_migration_compatibility import evaluate


@pytest.mark.parametrize(
    ("type_expression", "default", "expected"),
    [
        ("sa.String(1)", "ab", "FAIL"),
        ("sa.String(length=1)", "ab", "FAIL"),
        ("sa.String(**{'length': 1})", "ab", "FAIL"),
        ("sa.String(length=unknown)", "a", "FAIL"),
        ("sa.String(1, length=2)", "a", "FAIL"),
        ("sa.String(1)", "я", "PASS"),
        ("sa.String(1)", "", "PASS"),
        ("sa.String()", "arbitrary length", "PASS"),
        ("sa.Text()", "arbitrary length", "PASS"),
        ("sa.Numeric(2, 1)", "99.9", "FAIL"),
        ("sa.Numeric(2, 1)", "9.99", "FAIL"),
        ("sa.Numeric(precision=2, scale=1)", "9.99", "FAIL"),
        ("sa.Numeric(precision=unknown)", "1", "FAIL"),
        ("sa.Numeric(2, 1)", "9.94", "PASS"),
        ("sa.Numeric(2, 1)", "-9.94", "PASS"),
        ("sa.Numeric(2, 3)", "0", "PASS"),
        ("sa.Numeric(2, 3)", "0.09", "PASS"),
        ("sa.Numeric(2, 3)", "0.0999", "FAIL"),
        ("sa.Numeric(2, -1)", "990", "PASS"),
        ("sa.Numeric(2, -1)", "995", "FAIL"),
        ("sa.Numeric()", "1e1000", "PASS"),
        ("sa.Numeric(2, 1)", "1e-20000", "FAIL"),
        ("sa.Numeric(2, 1)", "1e-16400", "FAIL"),
        ("sa.Numeric(2, 1)", "1e-16383", "PASS"),
        ("sa.Float()", "1e1000", "FAIL"),
        ("sa.Float()", "1e-1000", "FAIL"),
        ("sa.Float()", "1e300", "PASS"),
        ("sa.Float()", "0", "PASS"),
        ("sa.Float(24)", "1e39", "FAIL"),
        ("sa.Float(24)", "1e-50", "FAIL"),
        ("sa.Float(24)", "1e38", "PASS"),
        ("sa.Float(24)", "1e-40", "PASS"),
        ("sa.Float(24)", "1e-45", "PASS"),
        ("sa.Float(24)", "1e-46", "FAIL"),
        ("sa.REAL()", "1e39", "FAIL"),
        ("sa.DOUBLE_PRECISION()", "1e39", "PASS"),
        ("sa.Boolean()", "nonsense", "FAIL"),
        ("sa.Boolean()", "true", "PASS"),
        ("sa.Boolean()", "false", "PASS"),
        ("sa.JSON()", "{broken", "FAIL"),
        ("sa.JSON()", "{}", "PASS"),
        ("sa.JSON()", "[]", "PASS"),
        ("sa.Date()", "2026-02-30", "FAIL"),
        ("sa.DateTime()", "not_timestamp", "FAIL"),
        ("sa.NVARCHAR(3)", "a", "FAIL"),
        ("sa.CHAR()", "ab", "FAIL"),
        ("sa.CHAR()", "a", "PASS"),
        ("sa.NCHAR()", "ab", "FAIL"),
        ("sa.NCHAR()", "a", "PASS"),
        ("sa.Integer(1)", "1", "FAIL"),
        ("sa.String(unknown=True)", "a", "FAIL"),
        ("sa.Numeric(unknown=True)", "1", "FAIL"),
        ("sa.Float(unknown=True)", "1", "FAIL"),
        ("sa.Boolean(unknown=True)", "true", "FAIL"),
    ],
)
def test_literal_default_respects_postgres_type_bounds(
    tmp_path: Path, type_expression: str, default: str, expected: str
) -> None:
    root = _copy_surface(tmp_path)
    _future(
        root,
        "op.add_column('accounts', "
        f"sa.Column('fresh', {type_expression}, server_default={default!r}))",
    )
    report = evaluate(root)
    assert report["status"] == expected, report


@pytest.mark.parametrize("type_expression", ["sa.Date()", "sa.DateTime()", "sa.LargeBinary()"])
def test_unsupported_populated_defaults_require_a_separate_proof(
    tmp_path: Path, type_expression: str
) -> None:
    root = _copy_surface(tmp_path)
    _future(
        root,
        "op.add_column('accounts', "
        f"sa.Column('fresh', {type_expression}, nullable=True, server_default='2026-01-01'))",
    )
    assert evaluate(root)["status"] == "FAIL"


@pytest.mark.parametrize("type_expression", ["sa.Date()", "sa.DateTime()", "sa.LargeBinary()"])
def test_unsupported_types_remain_additive_without_populated_defaults(
    tmp_path: Path, type_expression: str
) -> None:
    root = _copy_surface(tmp_path)
    _future(
        root,
        "op.add_column('accounts', "
        f"sa.Column('fresh', {type_expression}, nullable=True, server_default=None))",
    )
    assert evaluate(root)["status"] == "PASS"


@pytest.mark.parametrize(
    ("type_expression", "default_expression", "expected"),
    [
        ("sa.Text()", "sa.text(\"'O''Brien'\")", "PASS"),
        ("sa.String(3)", "sa.text(\"'long'\")", "FAIL"),
        ("sa.Text()", 'sa.text("CURRENT_TIMESTAMP")', "FAIL"),
        ("sa.Integer()", "sa.text(\"'oops'\")", "FAIL"),
        ("sa.Integer()", "sa.text(\"'42'\")", "PASS"),
        ("sa.Text()", "sa.text(\"'x'; SELECT 1\")", "FAIL"),
        ("sa.Text()", "'\\ud800'", "FAIL"),
    ],
)
def test_sqltext_default_requires_a_proven_literal_value(
    tmp_path: Path, type_expression: str, default_expression: str, expected: str
) -> None:
    root = _copy_surface(tmp_path)
    _future(
        root,
        "op.add_column('accounts', "
        f"sa.Column('fresh', {type_expression}, nullable=True, server_default={default_expression}))",
    )
    report = evaluate(root)
    assert report["status"] == expected, report


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        (
            "sa.Column('fresh', sa.Text(), nullable=False, server_default=sa.text(\"'ready'\"))",
            "PASS",
        ),
        (
            "sa.Column('fresh', sa.Text(), nullable=False, server_default=sa.text(\"'O''Brien'\"))",
            "PASS",
        ),
        (
            "sa.Column('fresh', sa.Text(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))",
            "FAIL",
        ),
        (
            "sa.Column('fresh', sa.Text(), nullable=False, server_default=sa.text(\"'unterminated\"))",
            "FAIL",
        ),
        ("sa.Column(sa.Integer(), name='fresh', nullable=True, server_default='1')", "PASS"),
        ("sa.Column(sa.Integer(), name='fresh', nullable=True, server_default='oops')", "FAIL"),
        (
            "sa.Column(sa.String(1), name='fresh', nullable=True, server_default='oversized')",
            "FAIL",
        ),
        ("sa.Column(type_=sa.Integer(), name='fresh', nullable=True, server_default='1')", "PASS"),
        ("sa.Column('fresh', type_=sa.Integer(), nullable=True, server_default='1')", "PASS"),
    ],
)
def test_literal_sqltext_default_and_named_column_full_evaluate(
    tmp_path: Path, column: str, expected: str
) -> None:
    root = _copy_surface(tmp_path)
    _future(root, f"op.add_column('accounts', {column})")
    report = evaluate(root)
    assert report["status"] == expected, (column, report["findings"])
