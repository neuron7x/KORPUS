from __future__ import annotations

from pathlib import Path

from korpus.config import OPERATIONAL_VARIABLES

ROOT = Path(__file__).resolve().parents[3]


def test_sqlite_recovery_environment_names_are_declared_operational_variables() -> None:
    required = {
        "KORPUS_BACKUP_SQLITE_PATH",
        "KORPUS_BACKUP_OBJECT_ROOT",
        "KORPUS_BACKUP_SECOND_DIR",
        "KORPUS_BACKUP_RETENTION_COUNT",
        "KORPUS_BACKUP_RETENTION_DAYS",
        "KORPUS_RECOVERY_ENVIRONMENT_CLASS",
    }
    assert required <= OPERATIONAL_VARIABLES


def test_sqlite_recovery_drill_is_fail_honest_about_fixture_class() -> None:
    text = (ROOT / "scripts/run_sqlite_recovery_drill.sh").read_text(encoding="utf-8")
    assert 'KORPUS_RECOVERY_ENVIRONMENT_CLASS="CI_FIXTURE"' in text
    assert "scripts/backup_sqlite.sh" in text
    assert "scripts/restore_sqlite.sh" in text
    assert "scripts/measure_recovery.py" in text
    assert "KORPUS_RECOVERY_PHASE=after-backup" in text


def test_recovery_measurement_uses_latest_protected_write_not_audit_only() -> None:
    text = (ROOT / "scripts/measure_recovery.py").read_text(encoding="utf-8")
    assert "def _latest_protected_write" in text
    assert "max(created_at)" in text and "FROM documents" in text
    assert "max(occurred_at)" in text and "FROM audit_events" in text
    assert "rpo_seconds = _interval(newest, newest_restored)" in text
