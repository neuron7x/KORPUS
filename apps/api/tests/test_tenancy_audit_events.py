"""What the audit chain says happened, and what it must never contain.

ACT-001 Workstream J. Two questions:

  is it recorded    every state change in the account and billing domains appends an event,
                    in the same commit as the change. The named actions are enumerated here
                    so a new one that forgets its event is visible as a gap rather than as
                    nothing.

  is it safe        no payload carries a webhook body, an email address, a signature or a
                    secret. An audit trail that holds customer data is a second place that
                    data can leak from, and it is the place nobody thinks to check.

The payload hash is the shape that satisfies both: it answers "was this the same event"
without holding the event.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from korpus.infrastructure.repository import audits
from sqlalchemy import select

from apps.api.tests.tenancy_fixtures import WEBHOOK_SECRET, build_tenancy, reader

#: Every state change in this domain, and the action it must append.
EXPECTED_ACTIONS = {
    "account.created",
    "account.disabled",
    "account.active",
    "plan.created",
    "subscription.created",
    "billing.event.applied",
    "billing.event.rejected",
}


def _events(tenancy: Any) -> list[dict[str, Any]]:
    with tenancy.repository.engine.connect() as connection:
        rows = connection.execute(
            select(
                audits.c.action,
                audits.c.actor_subject,
                audits.c.resource_type,
                audits.c.resource_id,
                audits.c.payload_json,
            ).order_by(audits.c.sequence)
        ).all()
    return [
        {
            "action": row[0],
            "actor": row[1],
            "resource_type": row[2],
            "resource_id": row[3],
            "payload": json.loads(row[4]),
        }
        for row in rows
    ]


def _exercise(tenancy: Any) -> None:
    """One pass through every state change the domain can make."""
    identity = reader("oidc|audited", frozenset({"training"}))
    account = tenancy.account_service.require_active_account(identity)
    tenancy.plan("standard", frozenset({"training"}))
    subscription = tenancy.subscription_service.start_subscription(
        identity.subject, account.id, "standard"
    )

    moment = datetime.now(UTC)
    applied = json.dumps(
        {
            "id": "audited-1",
            "type": "subscription.activated",
            "occurred_at": moment.isoformat(),
            "data": {
                "reference": str(subscription.id),
                "period_start": moment.isoformat(),
                "period_end": (moment + timedelta(days=30)).isoformat(),
                "customer_email": "soldier@example.org",
                "card_last4": "4242",
            },
        }
    ).encode("utf-8")
    tenancy.subscription_service.handle_event(applied, tenancy.provider.sign(applied))

    rejected = json.dumps(
        {
            "id": "audited-2",
            "type": "subscription.activated",
            "occurred_at": moment.isoformat(),
            "data": {"reference": "00000000-0000-0000-0000-000000000000"},
        }
    ).encode("utf-8")
    tenancy.subscription_service.handle_event(rejected, tenancy.provider.sign(rejected))

    tenancy.account_service.disable(reader("operator"), account.id, reason="rotation")
    tenancy.account_service.enable(reader("operator"), account.id, reason="returned")


def test_every_state_change_appends_its_own_audit_event(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        _exercise(tenancy)
        actions = {event["action"] for event in _events(tenancy)}
        missing = sorted(EXPECTED_ACTIONS - actions)
        assert not missing, f"these state changes left no audit event: {missing}"
        assert tenancy.repository.verify_audit().valid
    finally:
        tenancy.close()


def test_no_audit_payload_carries_a_secret_or_a_customer_detail(tmp_path: Path) -> None:
    """The webhook body carried an email and a card suffix. Neither may reach the chain."""
    tenancy = build_tenancy(tmp_path)
    try:
        _exercise(tenancy)
        forbidden = (WEBHOOK_SECRET, "soldier@example.org", "4242", "card_last4")
        for event in _events(tenancy):
            serialised = json.dumps(event["payload"], ensure_ascii=False)
            for needle in forbidden:
                assert needle not in serialised, (
                    f"{event['action']} put {needle!r} into the audit chain"
                )
    finally:
        tenancy.close()


def test_a_billing_event_is_recorded_by_hash_and_never_by_body(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        _exercise(tenancy)
        billing = [
            event for event in _events(tenancy) if event["action"].startswith("billing.event.")
        ]
        assert billing, "no billing event reached the audit chain"
        for event in billing:
            payload = event["payload"]
            assert len(payload["payload_sha256"]) == 64
            assert "data" not in payload and "body" not in payload
            assert payload["interpretation"], "an audit event with no interpretation"
    finally:
        tenancy.close()


def test_an_audit_actor_holds_no_reading_rights(tmp_path: Path) -> None:
    """The subject is named so the event can be attributed, not so it can read anything."""
    import pytest
    from korpus.application.policy import AuthorizationError, PolicyEngine
    from korpus.infrastructure.tenancy_repository import system_actor

    actor = system_actor("billing:deterministic")
    assert actor.roles == frozenset()
    with pytest.raises(AuthorizationError):
        PolicyEngine().require(actor, "answer:read")

    tenancy = build_tenancy(tmp_path)
    try:
        _exercise(tenancy)
        subjects = {event["actor"] for event in _events(tenancy)}
        assert "billing:deterministic" in subjects
        assert "oidc|audited" in subjects
    finally:
        tenancy.close()


def test_a_rejected_event_is_recorded_with_the_reason_it_was_rejected(
    tmp_path: Path,
) -> None:
    """A refusal that left no trace cannot be told apart from an event that never arrived."""
    tenancy = build_tenancy(tmp_path)
    try:
        _exercise(tenancy)
        rejected = [
            event for event in _events(tenancy) if event["action"] == "billing.event.rejected"
        ]
        assert rejected
        assert rejected[0]["payload"]["detail"]
        assert rejected[0]["payload"]["provider_event_id"] == "audited-2"
    finally:
        tenancy.close()
