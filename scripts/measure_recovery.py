#!/usr/bin/env python3
"""Measure a backup/restore drill without promoting fixture evidence to production.

RTO is restore plus verification time; RPO is measured from writes made after backup.
The report records scale, source and release so production assurance can reject a CI
fixture even when the restore itself succeeds.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))
from check_serving_freshness import topology_environment_class  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from korpus.application.recovery import (  # noqa: E402
    PRODUCTION_LIKE_MINIMUM_BYTES,
    PRODUCTION_LIKE_MINIMUM_ROWS,
)
from release_identity import release_tag  # noqa: E402

OUTPUT = ROOT / "var/recovery-report.json"


def _scalar(engine: Engine, statement: str) -> int:
    with engine.begin() as connection:
        # Row-level security reads the subject from session settings, and `set_config` is
        # PostgreSQL's. SQLite has no RLS at all, so there is nothing to tell — and the
        # drill has to run there, because the deployment that is actually serving keeps
        # its corpus in SQLite. Calling it unconditionally made this tool measurable only
        # on the deployment it was not measuring.
        if connection.dialect.name == "postgresql":
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


def _moment(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _interval(newest: object, newest_restored: object) -> float | None:
    """How far the restored copy sits behind the source, or None if either is silent.

    Absent is reported as absent rather than as zero: zero reads as "lost nothing", which
    is a claim, and no timestamp is not one.
    """
    left, right = _moment(newest), _moment(newest_restored)
    if left is None or right is None:
        return None
    if left.tzinfo is None or right.tzinfo is None:
        left, right = left.replace(tzinfo=None), right.replace(tzinfo=None)
    return (left - right).total_seconds()


def _engine_version(engine: Engine) -> str:
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            return str(connection.execute(text("SHOW server_version")).scalar_one())
        return str(connection.execute(text("SELECT sqlite_version()")).scalar_one())


def _latest_protected_write(engine: Engine) -> datetime | None:
    """Newest durable write across the document and audit streams."""
    statement = """
        SELECT max(ts) FROM (
            SELECT max(created_at) AS ts FROM documents
            UNION ALL SELECT max(occurred_at) AS ts FROM audit_events
        ) AS protected_writes
    """
    with engine.begin() as connection:
        return _moment(connection.execute(text(statement)).scalar_one_or_none())


def _database_path(url: str) -> str | None:
    """Файл бази з URL SQLite, або None для інших рушіїв: у них предмет не файл."""
    marker = "sqlite:///"
    if not url.startswith(marker):
        return None
    return "/" + url[len(marker) :].lstrip("/")


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
    engine_version = _engine_version(restored)
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

    # Use every protected write stream; audit-only RPO can read zero while documents are lost.
    newest = _latest_protected_write(source)
    newest_restored = _latest_protected_write(restored)
    rpo_seconds = _interval(newest, newest_restored)

    # Той самий інваріант, що й у навантаженні: PRODUCTION_LIKE віддає ВИМІР оголошеної
    # топології, змінна може лише послабити. Інакше `KORPUS_RECOVERY_ENVIRONMENT_CLASS=
    # PRODUCTION` робив би навчання на порожньому дереві доказом про продакшен.
    requested = os.getenv("KORPUS_RECOVERY_ENVIRONMENT_CLASS", "CI_FIXTURE")
    # Предмет виміру — база, яку навчання справді торкалось. Без цього прогін на копії
    # отримував би клас продакшену лише за те, що поруч живий сервіс.
    measured = topology_environment_class(ROOT, database=_database_path(source_url))
    environment_class = (
        requested
        if requested not in {"PRODUCTION_LIKE", "PRODUCTION"}
        else measured["environment_class"]
    )
    # Клас МАСШТАБУ — не клас середовища. Виміряно 04.09.2026: пілотна топологія
    # засвідчена як PRODUCTION_LIKE, і саме з цього рядок виводив `scale_class:
    # production-like` — на 259 документах і 19 МБ. Споживач (`classify_recovery`)
    # відмовив як OVERSTATED_SCALE і мав рацію: топологія й обсяг — різні предмети,
    # а тут вони жили під одним іменем. Підлога береться З ТОГО Ж модуля, що судить,
    # тож двох оголошень порогу не існує.
    scale_class = (
        "production-like"
        if int(manifest["plaintext_bytes"]) >= PRODUCTION_LIKE_MINIMUM_BYTES
        or document_rows >= PRODUCTION_LIKE_MINIMUM_ROWS
        else "ci-fixture"
    )
    report = {
        "schema_version": 2,
        "status": "PASS",
        "scale_class": scale_class,
        "environment_class": environment_class,
        "environment_class_requested": requested,
        "environment_class_basis": measured["basis"],
        "source_tree_sha256": compute_source_digest(ROOT),
        "release": release_tag(),
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
            "newest_source_write": None if newest is None else newest.isoformat(),
            "newest_restored_write": None
            if newest_restored is None
            else newest_restored.isoformat(),
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
