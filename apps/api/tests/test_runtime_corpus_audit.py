from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "audit_runtime_corpus", ROOT / "scripts/audit_runtime_corpus.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _database(path: Path, version: str, *, embeddings: int = 0) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE documents (id TEXT PRIMARY KEY);
        CREATE TABLE document_versions (
            id TEXT PRIMARY KEY, review_state TEXT NOT NULL, object_key TEXT NOT NULL
        );
        CREATE TABLE evidence_spans (id TEXT PRIMARY KEY);
        CREATE TABLE span_embeddings (span_id TEXT);
        INSERT INTO documents VALUES ('doc-1');
        INSERT INTO evidence_spans VALUES ('span-1');
        """
    )
    connection.execute(
        "INSERT INTO document_versions VALUES (?, 'approved', 'unused/object')", (version,)
    )
    for _ in range(embeddings):
        connection.execute("INSERT INTO span_embeddings VALUES ('span-1')")
    connection.commit()
    connection.close()
    return path


def _reference(path: Path, holders: list[str]) -> Path:
    case = {"id": "ret-1", "kind": "retrieval", "must_cite_one_of_if_answered": holders}
    path.write_text(json.dumps(case) + "\n", "utf-8")
    return path


def test_complete_reference_version_coverage_passes_without_semantic_mode(tmp_path: Path) -> None:
    report = MODULE.audit(
        _database(tmp_path / "corpus.db", "version-1"),
        _reference(tmp_path / "reference.jsonl", ["version-1", "duplicate-version"]),
    )

    assert report["status"] == "PASS"
    assert report["reference_coverage"]["coverage_ratio"] == 1.0
    assert report["counts"]["span_embeddings"] == 0


def test_smoke_database_fails_when_frozen_reference_versions_are_absent(tmp_path: Path) -> None:
    report = MODULE.audit(
        _database(tmp_path / "corpus.db", "unrelated-version"),
        _reference(tmp_path / "reference.jsonl", ["canonical-version"]),
    )

    assert report["status"] == "FAIL"
    assert report["checks"]["reference_versions_complete"] is False
    assert report["reference_coverage"]["missing_case_ids"] == ["ret-1"]


def test_required_semantic_mode_fails_without_one_vector_per_span(tmp_path: Path) -> None:
    report = MODULE.audit(
        _database(tmp_path / "corpus.db", "version-1"),
        _reference(tmp_path / "reference.jsonl", ["version-1"]),
        require_embeddings=True,
    )

    assert report["status"] == "FAIL"
    assert report["checks"]["embeddings_present_if_required"] is False


def test_sqlite_url_is_resolved_without_losing_the_absolute_path(tmp_path: Path) -> None:
    expected = tmp_path / "corpus.db"
    assert MODULE.database_path(f"sqlite:///{expected}") == expected


def test_object_store_is_verified_by_content_address(tmp_path: Path) -> None:
    database = _database(tmp_path / "corpus.db", "version-1")
    connection = sqlite3.connect(database)
    connection.execute("UPDATE document_versions SET object_key = 'aa/bb/not-the-digest'")
    connection.commit()
    connection.close()
    object_root = tmp_path / "objects"
    source = object_root / "aa/bb/not-the-digest"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")

    report = MODULE.audit(
        database,
        _reference(tmp_path / "reference.jsonl", ["version-1"]),
        object_root=object_root,
    )

    assert report["status"] == "FAIL"
    assert report["checks"]["referenced_object_hashes_valid"] is False
