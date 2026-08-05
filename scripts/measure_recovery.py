#!/usr/bin/env python3
"""Measure a backup/restore drill and record what the measurement is worth.

Run inside the PostgreSQL CI job, after `restore_postgres.sh` has produced a restored
database. Two clocks matter and they measure different things:

    RTO — wall time from the start of the restore command to the moment the restored
          database answers the verification queries. This is the number the runbook
          asked for and nobody recorded.

    RPO — the interval of writes a restore loses. Measured, not assumed: events are
          appended to the *source* database after the backup is taken, and the drill
          counts how many of them are absent from the restored copy, together with the
          span between the backup and the last of them.

The output is deliberately a report about a fixture. `korpus.application.recovery`
refuses to let it claim otherwise.

Usage:
  KORPUS_RECOVERY_SOURCE_URL=...  the database the backup was taken from
  KORPUS_RECOVERY_RESTORED_URL=... the database restored from it
  KORPUS_RECOVERY_BACKUP_PATH=...  the encrypted backup file
  KORPUS_RECOVERY_RESTORE_SECONDS=... wall seconds the restore command took
  python3 scripts/measure_recovery.py
"""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "var/recovery-report.json"


def _scalar(engine, statement: str) -> int:
    with engine.begin() as connection:
        for setting, value in (
            ("korpus.subject", "recovery-drill"),
            ("korpus.roles", "admin,user"),
            ("korpus.clearance", "3"),
            ("korpus.corpora", "public,restricted-demo"),
            ("korpus.classifications", "public,internal,restricted"),
        ):
            connection.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": setting, "value": value},
            )
        return int(connection.execute(text(statement)).scalar_one())


def main() -> int:
    source_url = os.environ["KORPUS_RECOVERY_SOURCE_URL"]
    restored_url = os.environ["KORPUS_RECOVERY_RESTORED_URL"]
    backup_path = Path(os.environ["KORPUS_RECOVERY_BACKUP_PATH"])
    restore_seconds = float(os.environ["KORPUS_RECOVERY_RESTORE_SECONDS"])

    manifest = json.loads(Path(f"{backup_path}.json").read_text(encoding="utf-8"))
    source = create_engine(source_url, pool_pre_ping=True)
    restored = create_engine(restored_url, pool_pre_ping=True)

    # The verification half of RTO: the restore is not over when pg_restore exits, it
    # is over when the database answers. Timed separately so a slow restore and a slow
    # first query are distinguishable rather than averaged into one opaque number.
    started = time.perf_counter()
    document_rows = _scalar(restored, "SELECT count(*) FROM documents")
    audit_rows = _scalar(restored, "SELECT count(*) FROM audit_events")
    engine_version = str(
        _scalar(restored, "SELECT current_setting('server_version_num')::int")
    )
    verify_seconds = time.perf_counter() - started

    source_audit_rows = _scalar(source, "SELECT count(*) FROM audit_events")

    # Writes made after the backup, counted in both databases. They exist so that
    # "lost nothing" is a result the drill could have failed to produce: a copy of a
    # database nobody wrote to loses nothing no matter how broken the restore is.
    written_after = _scalar(
        source,
        "SELECT count(*) FROM documents WHERE canonical_title LIKE 'recovery-drill-post %'",
    )
    survived_after = _scalar(
        restored,
        "SELECT count(*) FROM documents WHERE canonical_title LIKE 'recovery-drill-post %'",
    )
    lost_events = max(source_audit_rows - audit_rows, 0)
    lost_documents = max(written_after - survived_after, 0)

    # RPO as an interval, not a count: how far back the restored copy sits behind the
    # source. Null when the source recorded no timestamp after the backup — absent is
    # reported as absent rather than as zero, which would read as "lost nothing".
    with source.begin() as connection:
        newest = connection.execute(
            text("SELECT max(occurred_at) FROM audit_events")
        ).scalar_one_or_none()
    with restored.begin() as connection:
        newest_restored = connection.execute(
            text("SELECT max(occurred_at) FROM audit_events")
        ).scalar_one_or_none()
    rpo_seconds = (
        (newest - newest_restored).total_seconds()
        if newest is not None and newest_restored is not None
        else None
    )

    report = {
        "schema_version": 1,
        "scale_class": "ci-fixture",
        "rto_seconds": round(restore_seconds + verify_seconds, 3),
        "restore_seconds": round(restore_seconds, 3),
        "verify_seconds": round(verify_seconds, 3),
        "rpo_seconds": None if rpo_seconds is None else round(rpo_seconds, 3),
        "lost_events": lost_events,
        "lost_documents": lost_documents,
        "provenance": {
            "backup_bytes": int(manifest["bytes"]),
            "plaintext_bytes": int(manifest["plaintext_bytes"]),
            "document_rows": document_rows,
            "audit_event_rows": audit_rows,
            "source_audit_event_rows": source_audit_rows,
            "writes_after_backup": written_after,
            "engine_version": engine_version,
            "measured_at": datetime.now(UTC).isoformat(),
            "backup_key_id": str(manifest["key_id"]),
        },
        "interpretation": (
            "Recovery time and loss measured against a CI fixture database. It is "
            "evidence that the drill runs and that the numbers are collected, not "
            "evidence about operational recovery: no RTO or RPO objective has been "
            "declared by anyone entitled to declare one (admission ground 2.9)."
        ),
    }
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    source.dispose()
    restored.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
