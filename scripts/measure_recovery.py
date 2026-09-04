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
from rls_context import bind as bind_rls_context  # noqa: E402

OUTPUT = ROOT / "var/recovery-report.json"


def _scalar(engine: Engine, statement: str, authz_url: str = "") -> int:
    with engine.begin() as connection:
        # Контекст RLS кладе БРОКЕР. Доти тут стояв `set_config('korpus.*')` — протокол,
        # який схема 0020 більше не читає, тож застосунковий логін бачив НУЛЬ рядків.
        # Наслідок був не помилкою, а хибним ЧИСЛОМ: `document_rows: 0`,
        # `writes_after_backup: 0` і, як вінець, `lost_documents: 0` — значення, яке не
        # могло вийти іншим. Виміряно 04.09.2026 і в CI, і локально на пілоті.
        # SQLite не має RLS: там нема чого класти й нема кому відмовляти.
        if connection.dialect.name == "postgresql":
            bind_rls_context(connection, authz_url, "recovery-drill")
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


def _latest_protected_write(engine: Engine, authz_url: str = "") -> datetime | None:
    """Newest durable write across the document and audit streams.

    ШОСТЕ місце, де потрібен брокер, і єдине, яке лишалось непереведеним. Знайдено
    незалежним верифікатором 04.09.2026 і виміряно на живому пілоті: `documents` має
    RLS, `audit_events` не має. Без прив'язаного контексту потік документів дає в RPO
    НУЛЬ внеску — не помилку, не виняток, просто зникає, — і `max` лишається журналом
    аудиту. Відновлення, яке втратило всі документи після бекапу, але цілком відновило
    ланцюг аудиту, дало б `rpo_seconds ≈ 0`, тобто «нічого не втрачено».

    Рядок, який стоїть над викликом цієї функції, застерігає рівно від цього:
    «audit-only RPO can read zero while documents are lost». Інваріант тримався не
    тому, що охоронявся, а тому, що на цих даних аудит новіший за документи.
    """
    statement = """
        SELECT max(ts) FROM (
            SELECT max(created_at) AS ts FROM documents
            UNION ALL SELECT max(occurred_at) AS ts FROM audit_events
        ) AS protected_writes
    """
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            bind_rls_context(connection, authz_url, "recovery-drill")
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
    # Брокер ОКРЕМИЙ для кожної бази: контекст RLS кладеться в ту базу, у якій рахують.
    # Один URL на дві бази означав би, що половина чисел про іншу базу — і мовчки нуль.
    source_authz = os.getenv("KORPUS_RECOVERY_SOURCE_AUTHZ_URL", "")
    restored_authz = os.getenv("KORPUS_RECOVERY_RESTORED_AUTHZ_URL", "")

    manifest = json.loads(Path(f"{backup_path}.json").read_text(encoding="utf-8"))
    source = create_engine(source_url, pool_pre_ping=True)
    restored = create_engine(restored_url, pool_pre_ping=True)

    # The verification half of RTO: the restore is not over when pg_restore exits, it
    # is over when the database answers. Timed separately so a slow restore and a slow
    # first query are distinguishable rather than averaged into one opaque number.
    started = time.perf_counter()
    document_rows = _scalar(restored, "SELECT count(*) FROM documents", restored_authz)
    audit_rows = _scalar(restored, "SELECT count(*) FROM audit_events", restored_authz)
    engine_version = _engine_version(restored)
    verify_seconds = time.perf_counter() - started

    source_audit_rows = _scalar(source, "SELECT count(*) FROM audit_events", source_authz)

    # Writes made after the backup, counted in both databases. They exist so that
    # "lost nothing" is a result the drill could have failed to produce: a copy of a
    # database nobody wrote to loses nothing no matter how broken the restore is.
    written_after = _scalar(
        source,
        "SELECT count(*) FROM documents WHERE canonical_title LIKE 'recovery-drill-post %'",
        source_authz,
    )
    survived_after = _scalar(
        restored,
        "SELECT count(*) FROM documents WHERE canonical_title LIKE 'recovery-drill-post %'",
        restored_authz,
    )
    # Симетрично до `lost_events`: ОБИДВІ сторони, а не лише відновлена. Третій
    # контрприклад верифікатора, 04.09.2026: `rpo_seconds = max(джерело) − max(копія)`
    # відповідає на питання «наскільки свіжий найновіший УЦІЛІЛИЙ запис», а не «скільки
    # втрачено». Виміряно на ізольованій базі: 10 документів у джерелі, 5 у копії,
    # втрачено середину — вістря ціле, RPO 0.000000. І жодне інше число звіту цього не
    # ловило: `document_rows` рахувався ЛИШЕ у відновленій базі, `lost_documents` — лише
    # у фікстурній підмножині `recovery-drill-post %`. Отже втрата звичайних документів
    # корпусу — не найновіших, не фікстурних — була невидима цілком.
    source_document_rows = _scalar(source, "SELECT count(*) FROM documents", source_authz)
    lost_events = max(source_audit_rows - audit_rows, 0)
    lost_documents = max(written_after - survived_after, 0)
    lost_documents_total = max(source_document_rows - document_rows, 0)

    # Use every protected write stream; audit-only RPO can read zero while documents are lost.
    newest = _latest_protected_write(source, source_authz)
    newest_restored = _latest_protected_write(restored, restored_authz)
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
        # Втрата ПО ВСЬОМУ корпусу, не лише по фікстурі навчання.
        "lost_documents_total": lost_documents_total,
        "provenance": {
            "backup_bytes": int(manifest["bytes"]),
            "plaintext_bytes": int(manifest["plaintext_bytes"]),
            "document_rows": document_rows,
            "source_document_rows": source_document_rows,
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
