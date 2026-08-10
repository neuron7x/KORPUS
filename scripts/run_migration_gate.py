#!/usr/bin/env python3
"""Apply Alembic from an empty database and verify parity with runtime metadata."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, inspect, select

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"
sys.path.insert(0, str(API / "src"))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="korpus-migration-") as temporary:
        database = Path(temporary) / "migration.db"
        url = f"sqlite:///{database}"
        environment = os.environ.copy()
        environment["KORPUS_DATABASE_URL"] = url
        environment["PYTHONPATH"] = str(API / "src")
        alembic_config = str(API / "alembic.ini")
        command = [sys.executable, "-m", "alembic", "-c", alembic_config, "upgrade", "head"]
        completed = subprocess.run(
            command,
            cwd=API,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.returncode != 0:
            print(completed.stdout)
            return 1

        # Tables attach themselves to the shared MetaData at import time, so the set
        # of "expected" tables is really the set of modules this file happens to have
        # imported. With only repository imported, ingestion_jobs was missing from
        # expectations while present in the database, and the gate reported
        # table_set_match=false — a red gate accusing the schema of a defect that
        # belonged to the gate. Every module that defines tables must be imported here.
        import korpus.infrastructure.ingestion_jobs  # noqa: F401  (registers tables)
        from korpus.application.provenance import PROVENANCE_KEY, stamp
        from korpus.infrastructure.repository import audit_heads, metadata

        engine = create_engine(url)
        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names())
        expected_tables = set(metadata.tables)
        ignored = {
            "alembic_version",
            "evidence_fts",
            "evidence_fts_config",
            "evidence_fts_content",
            "evidence_fts_data",
            "evidence_fts_docsize",
            "evidence_fts_idx",
        }
        table_failures: dict[str, object] = {}
        for table_name in sorted(expected_tables):
            actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
            expected_columns = set(metadata.tables[table_name].columns.keys())
            if actual_columns != expected_columns:
                table_failures[table_name] = {
                    "missing": sorted(expected_columns - actual_columns),
                    "unexpected": sorted(actual_columns - expected_columns),
                }
        with engine.connect() as connection:
            head = connection.execute(select(audit_heads.c.sequence, audit_heads.c.head_hash)).one()
        search_index_present = "evidence_fts" in actual_tables
        report = {
            "migration": "head",
            "tables_expected": sorted(expected_tables),
            "tables_actual": sorted(actual_tables - ignored),
            "table_set_match": expected_tables == (actual_tables - ignored),
            "column_failures": table_failures,
            "audit_head_seeded": head.sequence == 0 and head.head_hash == "0" * 64,
            "sqlite_fts5_present": search_index_present,
            PROVENANCE_KEY: stamp(ROOT, "scripts/run_migration_gate.py"),
        }
        output = ROOT / "var/migration-report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if (
            report["table_set_match"]
            and not table_failures
            and report["audit_head_seeded"]
            and report["sqlite_fts5_present"]
        ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
