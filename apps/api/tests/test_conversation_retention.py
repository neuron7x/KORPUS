"""How long a soldier's questions are kept, and what an undeclared policy reports as.

The state that matters most here is the one nobody thinks to test: no window configured.
That is not "keep for ever, which is fine" — it is nobody having decided, and a report that
renders it green is how the decision never gets made. `NOT_DECLARED` is asserted first,
because it is the state the system is actually in today.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from korpus.application.conversation_retention import (
    MAXIMUM_RETENTION_DAYS,
    MINIMUM_RETENTION_DAYS,
    Disposition,
    InvalidRetentionWindow,
    RetentionState,
    plan_retention,
    validate_window,
)

from apps.api.tests.tenancy_fixtures import build_tenancy, reader

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def _aged(days: int) -> tuple:
    return uuid4(), NOW - timedelta(days=days)


def test_no_declared_window_is_reported_as_undecided_not_as_compliant() -> None:
    plan = plan_retention([_aged(4000)], window_days=None, now=NOW)
    assert plan.state is RetentionState.NOT_DECLARED
    assert plan.status == "NOT_DECLARED"
    assert plan.expired == ()
    # And the two empty states are distinguishable, which is the whole reason `state` is
    # carried beside the list.
    declared = plan_retention([_aged(1)], window_days=30, now=NOW)
    assert declared.expired == ()
    assert declared.status == "NOTHING_DUE"
    assert declared.status != plan.status


def test_age_is_measured_from_the_last_activity_not_from_creation() -> None:
    """A conversation somebody returned to yesterday is current, however old it is."""
    plan = plan_retention([_aged(2), _aged(400)], window_days=90, now=NOW)
    dispositions = {item.disposition for item in plan.decisions}
    assert dispositions == {Disposition.KEEP, Disposition.EXPIRED}
    expired = plan.expired
    assert len(expired) == 1
    assert expired[0].age_days == 400
    assert "beyond the declared 90" in expired[0].reason


def test_the_boundary_keeps_rather_than_deletes() -> None:
    """Exactly at the window is inside it. A rounding error must not erase a shift."""
    plan = plan_retention([_aged(90)], window_days=90, now=NOW)
    assert plan.expired == ()
    assert plan_retention([_aged(91)], window_days=90, now=NOW).expired


def test_an_impossible_window_is_refused_rather_than_clamped() -> None:
    with pytest.raises(InvalidRetentionWindow, match="shift is still running"):
        validate_window(MINIMUM_RETENTION_DAYS - 1)
    with pytest.raises(InvalidRetentionWindow, match="for ever"):
        validate_window(MAXIMUM_RETENTION_DAYS + 1)
    assert validate_window(MINIMUM_RETENTION_DAYS) == MINIMUM_RETENTION_DAYS
    assert validate_window(MAXIMUM_RETENTION_DAYS) == MAXIMUM_RETENTION_DAYS


def test_a_naive_timestamp_is_read_as_utc_rather_than_crashing() -> None:
    """SQLite hands back naive datetimes; a retention job must not die on a dialect."""
    plan = plan_retention(
        [(uuid4(), datetime(2020, 1, 1, 0, 0))], window_days=30, now=NOW
    )
    assert len(plan.expired) == 1


def test_the_report_names_what_it_would_delete(tmp_path: Path) -> None:
    plan = plan_retention([_aged(500)], window_days=30, now=NOW)
    report = plan.as_report()
    assert report["status"] == "PLANNED"
    assert report["window_days"] == 30
    assert len(report["expired"]) == 1
    assert report["interpretation"]


def test_deleting_removes_the_named_conversations_and_nothing_else(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        owner = tenancy.account_service.require_active_account(reader("oidc|retained"))
        keep = tenancy.conversation_service.create(owner, "лишити")
        drop = tenancy.conversation_service.create(owner, "видалити")
        tenancy.conversation_service.record_question(owner, drop.id, "старе питання")
        tenancy.conversation_service.record_question(owner, keep.id, "свіже питання")

        removed = tenancy.conversations.delete_conversations([drop.id])

        assert removed == 1, "the count came from the cascade rather than from the delete"
        remaining = tenancy.conversation_service.list_conversations(owner).items
        assert [item.id for item in remaining] == [keep.id]
        assert len(tenancy.conversation_service.messages(owner, keep.id).items) == 1
    finally:
        tenancy.close()


def test_deleting_nothing_is_not_an_error(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        assert tenancy.conversations.delete_conversations([]) == 0
    finally:
        tenancy.close()


def test_the_activity_listing_spans_every_account(tmp_path: Path) -> None:
    """Retention is an operator's job over the whole table, unlike every request read."""
    tenancy = build_tenancy(tmp_path)
    try:
        first = tenancy.account_service.require_active_account(reader("oidc|one"))
        second = tenancy.account_service.require_active_account(reader("oidc|two"))
        tenancy.conversation_service.create(first, "перша")
        tenancy.conversation_service.create(second, "друга")

        listed = tenancy.conversations.all_conversations_by_activity()

        assert len(listed) == 2
        assert all(moment.tzinfo is not None for _id, moment in listed)
    finally:
        tenancy.close()


def _run(database: Path, *arguments: str, window: str | None = None) -> tuple[int, dict]:
    environment = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(ROOT / "apps/api/src"),
        "KORPUS_DATABASE_URL": f"sqlite:///{database}",
        # The same key and anchor the fixture used. A different key is not a test-setup
        # detail: the verifier recomputes every HMAC with the key the process holds, so
        # signing one event with another key breaks the whole chain — which is what the
        # chain is for, and what the first run of this test demonstrated.
        "KORPUS_AUDIT_HMAC_KEY": "cli-audit-key",
        "KORPUS_AUDIT_ANCHOR_PATH": str(database.parent / "cli-anchor.json"),
    }
    if window is not None:
        environment["KORPUS_CONVERSATION_RETENTION_DAYS"] = window
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/conversation_retention.py"),
         "--out", str(database.parent / "report.json"), *arguments],
        capture_output=True, text=True, check=False, env=environment, timeout=300,
    )
    body = json.loads(completed.stdout) if completed.stdout.strip() else {}
    return completed.returncode, body


def test_the_script_reports_an_undeclared_policy_as_a_finding(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path, name="cli")
    owner = tenancy.account_service.require_active_account(reader("oidc|cli"))
    tenancy.conversation_service.create(owner, "розмова")
    tenancy.close()

    code, report = _run(tmp_path / "cli.db")

    assert code == 2, "an undeclared retention policy exited as though it were a pass"
    assert report["status"] == "NOT_DECLARED"


def test_the_script_refuses_to_apply_a_policy_nobody_declared(tmp_path: Path) -> None:
    """`--apply` with no window would delete everything or nothing by an unchosen default."""
    tenancy = build_tenancy(tmp_path, name="cli")
    owner = tenancy.account_service.require_active_account(reader("oidc|cli"))
    conversation = tenancy.conversation_service.create(owner, "розмова")
    tenancy.close()

    code, report = _run(tmp_path / "cli.db", "--apply")

    assert code == 2
    assert report["applied"] is False
    assert "nobody has declared" in report["detail"]

    tenancy = build_tenancy(tmp_path, name="cli")
    try:
        survivors = tenancy.conversations.all_conversations_by_activity()
        assert [item[0] for item in survivors] == [conversation.id]
    finally:
        tenancy.close()


def test_the_script_deletes_only_with_a_window_and_an_explicit_apply(tmp_path: Path) -> None:
    from korpus.domain.tenancy import MessageRecord, MessageRole
    from korpus.infrastructure.tenancy_schema import conversations as table
    from sqlalchemy import update

    tenancy = build_tenancy(tmp_path, name="cli")
    owner = tenancy.account_service.require_active_account(reader("oidc|cli"))
    old = tenancy.conversation_service.create(owner, "давня")
    fresh = tenancy.conversation_service.create(owner, "свіжа")
    tenancy.conversations.append_message(
        owner.id,
        MessageRecord(conversation_id=old.id, role=MessageRole.USER, raw_text="давнє",
                      created_at=datetime.now(UTC)),
    )
    with tenancy.repository.engine.begin() as connection:
        connection.execute(
            update(table).where(table.c.id == str(old.id)).values(
                updated_at=datetime.now(UTC) - timedelta(days=400)
            )
        )
    tenancy.close()

    # Planned, not applied: the default run must never delete.
    code, report = _run(tmp_path / "cli.db", window="90")
    assert code == 1
    assert report["status"] == "PLANNED"
    assert len(report["expired"]) == 1
    assert report["applied"] is False

    code, report = _run(tmp_path / "cli.db", "--apply", window="90")
    assert code == 0
    assert report["applied"] is True
    assert report["conversations_deleted"] == 1
    assert report["messages_deleted"] == 1

    tenancy = build_tenancy(tmp_path, name="cli")
    try:
        survivors = [item[0] for item in tenancy.conversations.all_conversations_by_activity()]
        assert survivors == [fresh.id]
        assert tenancy.repository.verify_audit().valid, "the deletion broke the audit chain"
    finally:
        tenancy.close()


def test_an_invalid_window_stops_the_job_rather_than_being_clamped(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path, name="cli")
    tenancy.close()

    for bad in ("1", "тридцять", "99999"):
        code, report = _run(tmp_path / "cli.db", "--apply", window=bad)
        assert code == 2, f"window {bad!r} was accepted"
        assert report["status"] == "INVALID_WINDOW"
