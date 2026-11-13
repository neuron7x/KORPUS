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
