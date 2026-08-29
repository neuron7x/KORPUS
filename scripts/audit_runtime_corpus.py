#!/usr/bin/env python3
"""Fail closed when a runtime is wired to an incomplete corpus.

Repository size is not corpus size: KORPUS stores source objects outside Git and may
point a perfectly healthy API at an empty smoke database.  This audit binds readiness
to database integrity, usable evidence and the frozen reference set's version holders.
It never mutates the database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]


def database_path(value: str) -> Path:
    """Accept a path or an absolute SQLite URL and reject every other backend."""
    if "://" not in value:
        return Path(value).expanduser().resolve()
    parsed = urlparse(value)
    if parsed.scheme != "sqlite" or parsed.netloc:
        raise ValueError("runtime corpus audit supports only local SQLite databases")
    return Path(unquote(parsed.path)).resolve()


def load_reference_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _database_state(database: Path) -> tuple[str, dict[str, int], set[str], set[str]]:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        counts = {
            "documents": _count(connection, "documents"),
            "versions": _count(connection, "document_versions"),
            "approved_versions": int(
                connection.execute(
                    "SELECT count(*) FROM document_versions WHERE review_state = 'approved'"
                ).fetchone()[0]
            ),
            "evidence_spans": _count(connection, "evidence_spans"),
            "span_embeddings": _count(connection, "span_embeddings"),
        }
        versions = {str(row[0]) for row in connection.execute("SELECT id FROM document_versions")}
        keys = {
            str(row[0]) for row in connection.execute("SELECT object_key FROM document_versions")
        }
        return integrity, counts, versions, keys
    finally:
        connection.close()


def _audit_objects(object_root: Path, object_keys: set[str]) -> dict[str, Any]:
    missing: list[str] = []
    mismatched: list[str] = []
    for key in sorted(object_keys):
        source = object_root / key
        if not source.is_file():
            missing.append(key)
            continue
        sha = hashlib.sha256()
        with source.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                sha.update(chunk)
        if sha.hexdigest() != Path(key).name:
            mismatched.append(key)
    return {
        "root": str(object_root),
        "referenced": len(object_keys),
        "missing": missing,
        "sha256_mismatches": mismatched,
    }


def audit(
    database: Path,
    reference_set: Path,
    *,
    object_root: Path | None = None,
    require_embeddings: bool = False,
) -> dict[str, Any]:
    checks: dict[str, bool] = {"database_exists": database.is_file()}
    if not checks["database_exists"]:
        return _report(database, checks, {}, {}, ["database does not exist"])

    integrity, counts, present_versions, object_keys = _database_state(database)

    retrieval = [
        case for case in load_reference_cases(reference_set) if case["kind"] == "retrieval"
    ]
    covered = [
        str(case["id"])
        for case in retrieval
        if present_versions.intersection(map(str, case["must_cite_one_of_if_answered"]))
    ]
    reference = {
        "retrieval_cases": len(retrieval),
        "covered_cases": len(covered),
        "coverage_ratio": len(covered) / len(retrieval) if retrieval else 0.0,
        "missing_case_ids": [
            str(case["id"]) for case in retrieval if str(case["id"]) not in covered
        ],
    }
    checks.update(
        {
            "sqlite_integrity": integrity == "ok",
            "documents_present": counts["documents"] > 0,
            "approved_versions_present": counts["approved_versions"] > 0,
            "evidence_present": counts["evidence_spans"] > 0,
            "reference_versions_complete": bool(retrieval) and len(covered) == len(retrieval),
            "embeddings_present_if_required": not require_embeddings
            or counts["span_embeddings"] >= counts["evidence_spans"] > 0,
        }
    )
    objects: dict[str, Any] = {}
    if object_root is not None:
        objects = _audit_objects(object_root, object_keys)
        checks["referenced_objects_present"] = not objects["missing"]
        checks["referenced_object_hashes_valid"] = not objects["sha256_mismatches"]
    blockers = [name for name, passed in checks.items() if not passed]
    report = _report(database, checks, counts, reference, blockers)
    report["object_store"] = objects
    return report


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _report(
    database: Path,
    checks: dict[str, bool],
    counts: dict[str, int],
    reference: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    digest = None
    if database.is_file():
        sha = hashlib.sha256()
        with database.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                sha.update(chunk)
        digest = sha.hexdigest()
    return {
        "schema_version": 1,
        "measured_at": datetime.now(UTC).isoformat(),
        "database": str(database),
        "database_sha256": digest,
        "counts": counts,
        "reference_coverage": reference,
        "checks": checks,
        "blockers": blockers,
        "status": "PASS" if not blockers else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, help="SQLite path or sqlite://// URL")
    parser.add_argument(
        "--reference-set", type=Path, default=ROOT / "evals/datasets/reference.jsonl"
    )
    parser.add_argument("--object-root", type=Path)
    parser.add_argument("--require-embeddings", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        report = audit(
            database_path(args.database),
            args.reference_set.resolve(),
            object_root=args.object_root.resolve() if args.object_root else None,
            require_embeddings=args.require_embeddings,
        )
    except (OSError, ValueError, sqlite3.Error, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"runtime corpus audit could not run: {error}") from error
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, "utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
