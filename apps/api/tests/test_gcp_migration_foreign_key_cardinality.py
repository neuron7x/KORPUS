"""Both FK collections must bind one local column to each referenced column."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations.ops import CreateForeignKeyOp

from apps.api.tests.test_gcp_migration_compatibility import _copy_surface, _future
from scripts.gcp.validate_migration_compatibility import evaluate


def _collection(names: list[str], form: str) -> str:
    return repr(tuple(names) if form == "tuple" else names)


def _foreign_key_call(kind: str, binding: str, local: str, remote: str) -> str:
    if kind == "operation":
        if binding == "positional":
            return f"op.create_foreign_key('fk', 'child', 'parent', {local}, {remote})"
        if binding == "mixed":
            return f"op.create_foreign_key('fk', 'child', referent_table='parent', local_cols={local}, remote_cols={remote})"
        if binding == "keyword":
            return f"op.create_foreign_key(constraint_name='fk', source_table='child', referent_table='parent', local_cols={local}, remote_cols={remote})"
        return f"op.create_foreign_key(**{{'constraint_name': 'fk', 'source_table': 'child', 'referent_table': 'parent', 'local_cols': {local}, 'remote_cols': {remote}}})"
    if binding == "positional":
        return f"sa.ForeignKeyConstraint({local}, {remote})"
    if binding == "mixed":
        return f"sa.ForeignKeyConstraint({local}, refcolumns={remote})"
    if binding == "keyword":
        return f"sa.ForeignKeyConstraint(columns={local}, refcolumns={remote})"
    return f"sa.ForeignKeyConstraint(**{{'columns': {local}, 'refcolumns': {remote}}})"


@pytest.mark.parametrize("kind", ["operation", "constructor"])
@pytest.mark.parametrize("binding", ["positional", "keyword", "mixed", "dict"])
@pytest.mark.parametrize("forms", [("list", "list"), ("tuple", "tuple"), ("list", "tuple")])
@pytest.mark.parametrize(("local_count", "remote_count"), [(2, 2), (1, 2), (2, 1)])
def test_foreign_key_paired_cardinality(
    tmp_path: Path,
    kind: str,
    binding: str,
    forms: tuple[str, str],
    local_count: int,
    remote_count: int,
) -> None:
    local = _collection(["a", "b"][:local_count], forms[0])
    remote_names = ["a", "b"] if kind == "operation" else ["parent.a", "parent.b"]
    remote = _collection(remote_names[:remote_count], forms[1])
    constraint = _foreign_key_call(kind, binding, local, remote)
    body = "op.create_table('parent', sa.Column('a', sa.Integer(), primary_key=True), sa.Column('b', sa.Integer(), primary_key=True))\n"
    child = "op.create_table('child', sa.Column('a', sa.Integer()), sa.Column('b', sa.Integer())"
    body += child + ")\n" + constraint if kind == "operation" else child + ", " + constraint + ")"
    root = _copy_surface(tmp_path)
    _future(root, body)
    report = evaluate(root)
    assert report["status"] == ("PASS" if local_count == remote_count else "FAIL"), report


@pytest.mark.parametrize("kind", ["operation", "constructor"])
@pytest.mark.parametrize(("local_count", "remote_count"), [(2, 2), (1, 2), (2, 1)])
def test_sqlalchemy_confirms_foreign_key_cardinality(
    kind: str, local_count: int, remote_count: int
) -> None:
    local, remote = ["a", "b"][:local_count], ["a", "b"][:remote_count]

    def build() -> sa.ForeignKeyConstraint:
        if kind == "operation":
            return CreateForeignKeyOp("fk", "child", "parent", local, remote).to_constraint()
        return sa.ForeignKeyConstraint(local, [f"parent.{name}" for name in remote])

    if local_count != remote_count:
        with pytest.raises(sa.exc.ArgumentError, match="number of constrained columns must match"):
            build()
    else:
        constraint = build()
        assert len(constraint.column_keys) == len(constraint.elements) == local_count
