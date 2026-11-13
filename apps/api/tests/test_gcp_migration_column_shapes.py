"""Unproved generators and compiler-interpolated arguments cannot alter old tables."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.tests.test_gcp_migration_compatibility import _copy_surface, _future
from scripts.gcp.validate_migration_compatibility import evaluate


@pytest.mark.parametrize(
    "column",
    [
        "sa.Column('x', sa.Integer(), sa.Computed('10 / id'), nullable=True)",
        "sa.Column('x', sa.Integer(), sa.Identity(always=True), nullable=True)",
        "sa.Column('x', sa.Integer(), sa.Sequence('existing_sequence'), nullable=True)",
        "sa.Column('x', sa.Integer(), sa.DefaultClause('7'), nullable=True)",
        "sa.Column('x', sa.Integer(), sa.FetchedValue(), nullable=True)",
        "sa.Column('x', sa.Integer(), sa.Text(), nullable=True)",
        "sa.Column('x', sa.Integer(), *[sa.Computed('10 / id')], nullable=True)",
        "sa.Column('x', sa.Integer(), server_onupdate=sa.text('mutate_existing()'))",
        "sa.Column('x', sa.Integer(), **{'server_onupdate': sa.text('mutate_existing()')})",
        "sa.Column('x', sa.Numeric(precision='2); UPDATE existing SET id=99; --'))",
        "sa.Column('x', sa.Numeric(scale='0); UPDATE existing SET id=99; --'))",
        "sa.Column('x', type_=sa.Numeric(**{'precision': '2); UPDATE existing SET id=99; --'}))",
        "sa.Column('x', sa.String(length='2); UPDATE existing SET id=99; --'))",
        "sa.Column('x', sa.Integer, name='duplicate')",
        "sa.Column('x', sa.Integer, type_=sa.Integer)",
    ],
)
def test_unproven_column_shapes_deny_on_existing_tables(tmp_path: Path, column: str) -> None:
    root = _copy_surface(tmp_path)
    _future(root, f"op.add_column('existing', {column})")
    report = evaluate(root)
    assert report["status"] == "FAIL", report


@pytest.mark.parametrize(
    "declaration",
    [
        "sa.Column('x', sa.Numeric(precision='2)); UPDATE existing SET id=99; --'))",
        "sa.Column('x', sa.Integer(), sa.Computed('mutate_existing()'))",
        "sa.Column('x', sa.Integer(), server_default=sa.text('0); UPDATE existing SET id=99; --'))",
        "sa.Column('x', sa.Integer()), prefixes=['TABLE extra(id integer); UPDATE existing SET id=99; CREATE']",
        "sa.Column('x', sa.Integer()), postgresql_partition_by='RANGE (x); UPDATE existing SET id=99; --'",
        "sa.Column('x', sa.Integer()), **{'prefixes': ['TEMPORARY']}",
    ],
)
def test_new_table_raw_fragments_deny(tmp_path: Path, declaration: str) -> None:
    root = _copy_surface(tmp_path)
    _future(root, f"op.create_table('fresh', {declaration})")
    report = evaluate(root)
    assert report["status"] == "FAIL", report


@pytest.mark.parametrize(
    "column",
    [
        "sa.Column('x', sa.Integer(), nullable=True)",
        "sa.Column('x', sa.Integer(), nullable=False, server_default='7')",
        "sa.Column('x', sa.Numeric(2, -1), nullable=True)",
        "sa.Column('x', sa.String(20), nullable=True)",
        "sa.Column('x', type_=sa.Integer, nullable=True)",
        "sa.Column(name='x', type_=sa.Integer, nullable=True)",
        "sa.Column('x', sa.DateTime(timezone=True), nullable=True)",
        "sa.Column('x', sa.Integer(), sa.CheckConstraint('x > 0'), nullable=True)",
    ],
)
def test_bounded_column_shapes_preserve_safe_additions(tmp_path: Path, column: str) -> None:
    root = _copy_surface(tmp_path)
    _future(root, f"op.add_column('existing', {column})")
    report = evaluate(root)
    assert report["status"] == "PASS", report
