"""Fail-closed branch controls for pinned migration proof and database admission.

SQLite/AST tests only; PostgreSQL integration and production gates remain separate.
"""

from __future__ import annotations

import ast
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from korpus.infrastructure import migration_admission as admission
from korpus.infrastructure import migration_baseline_proof as proof

VERSIONS = "apps/api/migrations/versions"
POLICY = "config/production/migration-policy.json"


def _write(root: Path, name: str, data: bytes) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _source(revision: str = "0001_base", parent: str | None = None) -> bytes:
    return f'''"""Passive fixture."""
from __future__ import annotations
from collections.abc import Sequence
from alembic import op
revision: str = {revision!r}
down_revision: str | None = {parent!r}
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
def upgrade() -> None:
    pass
def downgrade() -> None:
    pass
'''.encode()


def test_valid_baseline_chain(tmp_path: Path) -> None:
    first, second = _source(), _source("0002_next", "0001_base")
    entries = {}
    for name, source in (("0001_base", first), ("0002_next", second)):
        path = f"{VERSIONS}/{name}.py"
        _write(tmp_path, path, source)
        entries[path] = hashlib.sha256(source).hexdigest()
    _write(
        tmp_path,
        POLICY,
        json.dumps(
            {
                "baseline_files": entries,
                "baseline_revision": "0002_next",
            }
        ).encode(),
    )
    baseline = proof.verify_baseline(tmp_path)
    assert baseline.chain == ("0001_base", "0002_next")
    assert proof.proven_baseline_forward(("0001_base",), "0002_next", baseline.chain)
    assert not proof.proven_baseline_forward(("0002_next",), "0001_base", baseline.chain)


def test_duplicate_json_policy_keys_fail(tmp_path: Path) -> None:
    _write(tmp_path, POLICY, b'{"baseline_files":{},"baseline_files":{}}')
    with pytest.raises(proof.BaselineProofError, match="PROOF_UNAVAILABLE"):
        proof.verify_baseline(tmp_path)


def test_baseline_requires_regular_source_not_symlink(tmp_path: Path) -> None:
    target = tmp_path / "original.py"
    target.write_bytes(_source())
    alias = tmp_path / VERSIONS / "0001_base.py"
    alias.parent.mkdir(parents=True, exist_ok=True)
    alias.symlink_to(target)
    with pytest.raises(proof.BaselineProofError, match="SOURCE_SYMLINK"):
        proof._read_source(tmp_path, str(alias.relative_to(tmp_path)))


@pytest.mark.parametrize(
    "assignment,value",
    [
        ("revision = 'x'", "x"),
        ("revision: str = 'x'", "x"),
        ("revision: str = None", None),
    ],
)
def test_literal_revision_assignments(assignment: str, value: str | None) -> None:
    assert proof._assignment(ast.parse(assignment), "revision") == value


@pytest.mark.parametrize(
    "assignment",
    [
        "revision = missing",
        "revision = 3",
        "revision = 'a'\nrevision = 'b'",
    ],
)
def test_nonliteral_or_duplicate_assignment_denied(assignment: str) -> None:
    with pytest.raises(proof.BaselineProofError, match="GRAPH_UNPROVEN"):
        proof._assignment(ast.parse(assignment), "revision")


@pytest.mark.parametrize(
    "records",
    [
        None,
        {},
        {"../traversal.py": "a" * 64},
        {f"{VERSIONS}/0001_base.py": "wrong-digest"},
    ],
)
def test_baseline_records_invalid_paths_and_digests_denied(tmp_path: Path, records: object) -> None:
    with pytest.raises(proof.BaselineProofError, match="POLICY_INVALID"):
        proof._records(tmp_path, records)


def test_missing_or_reused_revision_identifier_denied(tmp_path: Path) -> None:
    bad = _source().replace(b"revision: str = '0001_base'", b"marker = 'x'")
    path = f"{VERSIONS}/0001_base.py"
    _write(tmp_path, path, bad)
    with pytest.raises(proof.BaselineProofError, match="GRAPH_UNPROVEN"):
        proof._records(tmp_path, {path: hashlib.sha256(bad).hexdigest()})
    second = f"{VERSIONS}/0002_next.py"
    duplicate = _source()
    _write(tmp_path, path, duplicate)
    _write(tmp_path, second, duplicate)
    with pytest.raises(proof.BaselineProofError, match="GRAPH_UNPROVEN"):
        proof._records(
            tmp_path,
            {
                path: hashlib.sha256(duplicate).hexdigest(),
                second: hashlib.sha256(duplicate).hexdigest(),
            },
        )


@pytest.mark.parametrize(
    "head,revisions",
    [
        (None, {"a": None}),
        ("missing", {"a": None}),
        ("b", {"a": "b", "b": "a"}),
        ("a", {"a": None, "b": None}),
    ],
)
def test_baseline_head_cycle_and_disconnected_denied(
    head: object, revisions: dict[str, str | None]
) -> None:
    with pytest.raises(proof.BaselineProofError, match=r"POLICY_INVALID|GRAPH_UNPROVEN"):
        proof._chain(revisions, head)


def test_policy_nonobject_denied(tmp_path: Path) -> None:
    _write(tmp_path, POLICY, b"[]")
    with pytest.raises(proof.BaselineProofError, match="POLICY_INVALID"):
        proof.verify_baseline(tmp_path)


@pytest.mark.parametrize(
    "source",
    [
        _source(parent="expected").replace(
            b"def upgrade()", b"branch_labels = 'forged'\ndef upgrade()"
        ),
        _source(parent="expected").replace(b"from alembic import op\n", b""),
        _source(parent="expected").replace(
            b"down_revision: str | None = 'expected'", b"down_revision: str | None = 'wrong'"
        ),
    ],
)
def test_future_revision_requires_passive_graph_and_imports(tmp_path: Path, source: bytes) -> None:
    _write(tmp_path, f"{VERSIONS}/0001_base.py", source)
    with pytest.raises(proof.BaselineProofError, match=r"INITIALIZATION_UNPROVEN|GRAPH_UNPROVEN"):
        proof.verify_passive_revision(tmp_path, "0001_base", "expected")


def test_valid_passive_revision(tmp_path: Path) -> None:
    _write(tmp_path, f"{VERSIONS}/0001_base.py", _source(parent="0002_next"))
    assert proof.verify_passive_revision(tmp_path, "0001_base", "0002_next").revision == "0001_base"


class _FakeDB:
    def __init__(self, dialect: str = "mysql", schema: str = "public", nonempty: bool = False):
        self.dialect = SimpleNamespace(name=dialect)
        self.schema = schema
        self.nonempty = nonempty
        self.calls: list[str] = []

    @contextmanager
    def begin(self):
        self.calls.append("begin")
        try:
            yield self
        finally:
            self.calls.append("end")

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append(sql)
        if "current_schema()" in sql:
            return SimpleNamespace(scalar_one=lambda: self.schema)
        if "SELECT EXISTS (" in sql:
            return SimpleNamespace(scalar_one=lambda: self.nonempty)
        return SimpleNamespace(scalar=lambda: None)


def _admit(connection, target: object = "0002_next", source_head: str = admission.BOOTSTRAP_HEAD):
    return admission.assert_online_admission(
        connection,
        target,
        source_head,
        frozenset({"0002_next", admission.BOOTSTRAP_HEAD}),
        proof.BaselineProof(("0001_base", "0002_next"), frozenset(), ()),
    )


def test_unsupported_migration_lock_fails_before_execution() -> None:
    db = _FakeDB()
    with (
        pytest.raises(
            admission.MigrationAdmissionError, match="DENIED_DATABASE_DIALECT_UNPROVEN"
        ),
        admission.migration_lock(db),
    ):
        pytest.fail("unsupported database must never pass lock gate")
    assert db.calls == ["begin", "end"]


def test_attached_sqlite_namespace_denied() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.connect() as db:
            assert admission._sqlite_empty(db) is True
            db.exec_driver_sql("ATTACH DATABASE ':memory:' AS foreign_catalog")
            assert admission._sqlite_empty(db) is False
            with pytest.raises(
                admission.MigrationAdmissionError, match="DENIED_RETIREMENT_UNPROVEN"
            ):
                _admit(db)
    finally:
        engine.dispose()


def test_source_head_mismatch_denied_without_query() -> None:
    with pytest.raises(admission.MigrationAdmissionError, match="DENIED_SOURCE_HISTORY_UNPROVEN"):
        _admit(_FakeDB("postgresql"), source_head="forged")


@pytest.mark.parametrize("target", [None, ("0002_next",), "unknown"])
def test_unproven_migration_target_denied_without_query(target: object) -> None:
    with pytest.raises(admission.MigrationAdmissionError, match="DENIED_MIGRATION_TARGET_UNPROVEN"):
        _admit(None, target)


def test_nonpublic_postgres_namespace_denied() -> None:
    db = _FakeDB("postgresql", schema="untrusted")
    with pytest.raises(
        admission.MigrationAdmissionError, match="DENIED_DATABASE_NAMESPACE_UNPROVEN"
    ):
        _admit(db)
    assert any("current_schema()" in sql for sql in db.calls)


def test_unsupported_online_dialect_denied() -> None:
    with pytest.raises(admission.MigrationAdmissionError, match="DENIED_DATABASE_DIALECT_UNPROVEN"):
        _admit(_FakeDB())


def test_positive_empty_sqlite_bootstrap() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.connect() as db:
            _admit(db)
    finally:
        engine.dispose()


def test_postgres_branch_oracle_nonproduction_fake() -> None:
    _admit(_FakeDB("postgresql", nonempty=False))
    with pytest.raises(admission.MigrationAdmissionError, match="DENIED_RETIREMENT_UNPROVEN"):
        _admit(_FakeDB("postgresql", nonempty=True))
