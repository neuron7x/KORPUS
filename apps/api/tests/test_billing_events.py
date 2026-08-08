"""Everything a payment provider can do to us, done on purpose.

ACT-001 Workstream C. Each test is a way a billing integration is known to fail in
production, and the assertion in every one of them is the same: *the subscription is not
where the event wanted it*.

  duplicate delivery      providers redeliver on timeout, on 5xx, on their own schedule.
  concurrent delivery     the same event twice at the same instant, which is what defeats
                          a SELECT-before-INSERT idempotency check.
  forged event            a body with no signature, or the wrong one.
  unknown subscription    an event naming something this system never created.
  malformed payload       truncated JSON, a non-object, an unmapped event type.
  invalid transition      canceled → active, the resurrection an attacker wants.
  replayed older event    a genuine, correctly signed event from last month.
  storage failure         the commit fails after the event was parsed and adjudicated.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from korpus.application.tenancy_ports import (
    BillingEventRejected,
    InvalidSubscriptionTransition,
)
from korpus.domain.tenancy import BillingEventResult, SubscriptionStatus
from sqlalchemy import func, select

from apps.api.tests.tenancy_fixtures import build_tenancy

#: The barrier only has to make the writers overlap; it is not the thing under test, and a
#: timeout on it measures how loaded the machine is rather than whether the race is handled.
#: Five seconds was enough on an idle laptop and not enough during a mutation run, which is
#: exactly when the suite is most likely to be running. Generous, because the cost of being
#: generous is nothing and the cost of being tight is a red build nobody can reproduce.
BARRIER_SECONDS = 60


#: Events are stamped relative to the real clock, not to a fixed date. The service
#: refuses an event older than the state it would move — replay resistance — and a fixture
#: pinned to a calendar date makes that rule fire against the fixture instead of against a
#: replay, which is a test that passes for the wrong reason on one side of noon.
def now() -> datetime:
    return datetime.now(UTC)


def _event(
    tenancy: Any,
    event_id: str,
    event_type: str,
    *,
    reference: str | None = None,
    subscription_id: str | None = None,
    occurred_at: datetime | None = None,
    period_end: datetime | None = None,
) -> tuple[bytes, str]:
    moment = occurred_at or now()
    body: dict[str, Any] = {
        "id": event_id,
        "type": event_type,
        "occurred_at": moment.isoformat(),
        "data": {
            "reference": reference,
            "subscription_id": subscription_id,
            "period_start": moment.isoformat(),
            "period_end": (period_end or moment + timedelta(days=30)).isoformat(),
        },
    }
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return payload, tenancy.provider.sign(payload)


def _account_with_subscription(tenancy: Any, subject: str = "oidc|payer") -> Any:
    account, _ = tenancy.accounts.ensure_account(subject)
    tenancy.plan("standard", frozenset({"training"}))
    return account, tenancy.subscription_service.start_subscription(
        subject, account.id, "standard"
    )


def test_a_verified_event_activates_and_is_recorded(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        _account, subscription = _account_with_subscription(tenancy)
        assert subscription.status is SubscriptionStatus.INCOMPLETE

        payload, signature = _event(
            tenancy, "evt-1", "subscription.activated", reference=str(subscription.id)
        )
        assert tenancy.subscription_service.handle_event(payload, signature) is (
            BillingEventResult.APPLIED
        )

        stored = tenancy.subscriptions.get_subscription(subscription.id)
        assert stored is not None
        assert stored.status is SubscriptionStatus.ACTIVE
        assert stored.current_period_end is not None
        assert tenancy.repository.verify_audit().valid
    finally:
        tenancy.close()


def test_a_redelivered_event_changes_nothing(tmp_path: Path) -> None:
    """The ordinary case, not the exotic one: every provider redelivers."""
    tenancy = build_tenancy(tmp_path)
    try:
        _account, subscription = _account_with_subscription(tenancy)
        payload, signature = _event(
            tenancy, "evt-dup", "subscription.activated", reference=str(subscription.id)
        )
        first = tenancy.subscription_service.handle_event(payload, signature)
        second = tenancy.subscription_service.handle_event(payload, signature)

        assert first is BillingEventResult.APPLIED
        assert second is BillingEventResult.DUPLICATE

        from korpus.infrastructure.tenancy_schema import billing_events

        with tenancy.repository.engine.connect() as connection:
            rows = connection.execute(
                select(func.count())
                .select_from(billing_events)
                .where(billing_events.c.provider_event_id == "evt-dup")
            ).scalar_one()
        assert rows == 1, "the same provider event was stored twice"
    finally:
        tenancy.close()


def test_two_concurrent_deliveries_apply_once(tmp_path: Path) -> None:
    """The case a SELECT-then-INSERT idempotency check gets wrong.

    Both deliveries read "not seen", both proceed, and the unique constraint is the only
    thing standing between that and a subscription extended twice.
    """
    tenancy = build_tenancy(tmp_path)
    try:
        _account, subscription = _account_with_subscription(tenancy)
        payload, signature = _event(
            tenancy, "evt-race", "subscription.activated", reference=str(subscription.id)
        )

        outcomes: list[BillingEventResult] = []
        failures: list[BaseException] = []
        start = threading.Barrier(4)

        def deliver() -> None:
            try:
                start.wait(timeout=BARRIER_SECONDS)
                outcomes.append(tenancy.subscription_service.handle_event(payload, signature))
            except BaseException as error:  # noqa: BLE001 - reported, not swallowed
                failures.append(error)

        threads = [threading.Thread(target=deliver) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=BARRIER_SECONDS)

        assert not failures, failures
        assert outcomes.count(BillingEventResult.APPLIED) == 1, outcomes

        from korpus.infrastructure.tenancy_schema import billing_events

        with tenancy.repository.engine.connect() as connection:
            rows = connection.execute(
                select(func.count())
                .select_from(billing_events)
                .where(billing_events.c.provider_event_id == "evt-race")
            ).scalar_one()
        assert rows == 1
    finally:
        tenancy.close()


def test_an_unsigned_event_is_refused(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        _account, subscription = _account_with_subscription(tenancy)
        payload, _signature = _event(
            tenancy, "evt-unsigned", "subscription.activated", reference=str(subscription.id)
        )
        with pytest.raises(BillingEventRejected):
            tenancy.subscription_service.handle_event(payload, None)
        with pytest.raises(BillingEventRejected):
            tenancy.subscription_service.handle_event(payload, "0" * 64)

        stored = tenancy.subscriptions.get_subscription(subscription.id)
        assert stored is not None and stored.status is SubscriptionStatus.INCOMPLETE
    finally:
        tenancy.close()


def test_a_tampered_body_no_longer_matches_its_signature(tmp_path: Path) -> None:
    """The signature covers the bytes. Changing one changes the other."""
    tenancy = build_tenancy(tmp_path)
    try:
        _account, subscription = _account_with_subscription(tenancy)
        payload, signature = _event(
            tenancy, "evt-tamper", "subscription.activated", reference=str(subscription.id)
        )
        tampered = payload.replace(b"subscription.activated", b"subscription.renewed\x20")
        with pytest.raises(BillingEventRejected):
            tenancy.subscription_service.handle_event(tampered, signature)
    finally:
        tenancy.close()


@pytest.mark.parametrize(
    "body",
    [
        b"{not json",
        b"[]",
        b'{"id": "x"}',
        b'{"id": "x", "type": "subscription.activated"}',
        b'{"id": "x", "type": "unknown.event", "data": {}}',
        b'{"type": "subscription.activated", "data": {}}',
    ],
)
def test_malformed_payloads_are_refused_and_change_nothing(tmp_path: Path, body: bytes) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        _account, subscription = _account_with_subscription(tenancy)
        signature = tenancy.provider.sign(body)
        with pytest.raises(BillingEventRejected):
            tenancy.subscription_service.handle_event(body, signature)
        stored = tenancy.subscriptions.get_subscription(subscription.id)
        assert stored is not None and stored.status is SubscriptionStatus.INCOMPLETE
    finally:
        tenancy.close()


def test_an_event_naming_an_unknown_subscription_is_recorded_and_refused(
    tmp_path: Path,
) -> None:
    """A forged event must not be able to bring a subscription into existence."""
    tenancy = build_tenancy(tmp_path)
    try:
        _account_with_subscription(tenancy)
        payload, signature = _event(
            tenancy, "evt-ghost", "subscription.activated", reference=str(uuid4())
        )
        assert tenancy.subscription_service.handle_event(payload, signature) is (
            BillingEventResult.REJECTED
        )

        from korpus.infrastructure.tenancy_schema import subscriptions

        with tenancy.repository.engine.connect() as connection:
            total = connection.execute(
                select(func.count()).select_from(subscriptions)
            ).scalar_one()
        assert total == 1, "a webhook created a subscription"

        recorded = tenancy.subscriptions.get_billing_event("deterministic", "evt-ghost")
        assert recorded is not None, "a rejected event left no trace"
        assert recorded.processing_result is BillingEventResult.REJECTED
    finally:
        tenancy.close()


def test_an_event_for_an_account_that_does_not_exist_cannot_start_a_subscription(
    tmp_path: Path,
) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        tenancy.plan("standard", frozenset({"training"}))
        with pytest.raises(BillingEventRejected):
            tenancy.subscription_service.start_subscription("nobody", uuid4(), "standard")
    finally:
        tenancy.close()


def test_a_canceled_subscription_cannot_be_reactivated(tmp_path: Path) -> None:
    """The resurrection. `CANCELED` is terminal, and a renewal is a new subscription."""
    tenancy = build_tenancy(tmp_path)
    try:
        _account, subscription = _account_with_subscription(tenancy)
        activate, activate_signature = _event(
            tenancy, "evt-a", "subscription.activated", reference=str(subscription.id)
        )
        tenancy.subscription_service.handle_event(activate, activate_signature)

        cancel, cancel_signature = _event(
            tenancy,
            "evt-c",
            "subscription.canceled",
            reference=str(subscription.id),
            occurred_at=now() + timedelta(minutes=1),
        )
        tenancy.subscription_service.handle_event(cancel, cancel_signature)
        assert tenancy.subscriptions.get_subscription(subscription.id).status is (
            SubscriptionStatus.CANCELED
        )

        revive, revive_signature = _event(
            tenancy,
            "evt-r",
            "subscription.activated",
            reference=str(subscription.id),
            occurred_at=now() + timedelta(minutes=2),
        )
        with pytest.raises(InvalidSubscriptionTransition):
            tenancy.subscription_service.handle_event(revive, revive_signature)

        assert tenancy.subscriptions.get_subscription(subscription.id).status is (
            SubscriptionStatus.CANCELED
        )
        recorded = tenancy.subscriptions.get_billing_event("deterministic", "evt-r")
        assert recorded is not None
        assert recorded.processing_result is BillingEventResult.REJECTED
    finally:
        tenancy.close()


def test_a_replayed_older_event_does_not_move_the_subscription_backwards(
    tmp_path: Path,
) -> None:
    """Correctly signed, genuinely ours, and a month out of date."""
    tenancy = build_tenancy(tmp_path)
    try:
        _account, subscription = _account_with_subscription(tenancy)
        activate, activate_signature = _event(
            tenancy,
            "evt-now",
            "subscription.activated",
            reference=str(subscription.id),
            occurred_at=now(),
        )
        tenancy.subscription_service.handle_event(activate, activate_signature)

        stale, stale_signature = _event(
            tenancy,
            "evt-old",
            "subscription.payment_failed",
            reference=str(subscription.id),
            occurred_at=now() - timedelta(days=40),
        )
        assert tenancy.subscription_service.handle_event(stale, stale_signature) is (
            BillingEventResult.REJECTED
        )
        assert tenancy.subscriptions.get_subscription(subscription.id).status is (
            SubscriptionStatus.ACTIVE
        )
    finally:
        tenancy.close()


def test_a_storage_failure_leaves_no_half_applied_event(tmp_path: Path) -> None:
    """The whole point of one commit: the event row and the state move together."""
    tenancy = build_tenancy(tmp_path)
    try:
        _account, subscription = _account_with_subscription(tenancy)
        payload, signature = _event(
            tenancy, "evt-boom", "subscription.activated", reference=str(subscription.id)
        )

        original = tenancy.repository.audit_in_connection

        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("audit write failed")

        tenancy.repository.audit_in_connection = explode  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError):
                tenancy.subscription_service.handle_event(payload, signature)
        finally:
            tenancy.repository.audit_in_connection = original  # type: ignore[method-assign]

        assert tenancy.subscriptions.get_subscription(subscription.id).status is (
            SubscriptionStatus.INCOMPLETE
        ), "the subscription moved without its event"
        assert tenancy.subscriptions.get_billing_event("deterministic", "evt-boom") is None, (
            "the event was recorded without its effect"
        )

        # And the redelivery still works, which is the property a half-write destroys.
        assert tenancy.subscription_service.handle_event(payload, signature) is (
            BillingEventResult.APPLIED
        )
    finally:
        tenancy.close()


def test_a_subscription_cannot_be_started_on_an_unknown_plan(tmp_path: Path) -> None:
    from korpus.application.tenancy_ports import PlanNotFound

    tenancy = build_tenancy(tmp_path)
    try:
        account, _ = tenancy.accounts.ensure_account("oidc|planless")
        with pytest.raises(PlanNotFound):
            tenancy.subscription_service.start_subscription("x", account.id, "nonexistent")
    finally:
        tenancy.close()


def test_the_webhook_secret_must_be_long_enough_to_be_a_secret() -> None:
    from korpus.infrastructure.deterministic_billing import DeterministicBillingProvider

    with pytest.raises(ValueError):
        DeterministicBillingProvider("short")


def test_an_oversized_payload_is_refused_before_it_is_parsed(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        payload = b"{" + b"x" * (64 * 1024 + 1)
        with pytest.raises(BillingEventRejected):
            tenancy.subscription_service.handle_event(payload, "irrelevant")
    finally:
        tenancy.close()


def test_the_first_event_records_the_providers_own_subscription_id(tmp_path: Path) -> None:
    """Later events arrive addressed by the provider's id, not by our reference.

    Without this the second event for a subscription is unlocatable, and the failure is
    silent: it is recorded as "names a subscription this system has never created", which
    reads like a forgery rather than like a missing link.
    """
    tenancy = build_tenancy(tmp_path)
    try:
        _account, subscription = _account_with_subscription(tenancy)
        first, first_signature = _event(
            tenancy,
            "evt-link",
            "subscription.activated",
            reference=str(subscription.id),
            subscription_id="sub_provider_9",
        )
        tenancy.subscription_service.handle_event(first, first_signature)

        stored = tenancy.subscriptions.get_subscription(subscription.id)
        assert stored is not None and stored.provider_subscription_id == "sub_provider_9"

        # And the second event, carrying only the provider's id, still lands.
        second, second_signature = _event(
            tenancy,
            "evt-link-2",
            "subscription.payment_failed",
            subscription_id="sub_provider_9",
            occurred_at=now() + timedelta(minutes=5),
        )
        assert tenancy.subscription_service.handle_event(second, second_signature) is (
            BillingEventResult.APPLIED
        )
        assert tenancy.subscriptions.get_subscription(subscription.id).status is (
            SubscriptionStatus.PAST_DUE
        )
    finally:
        tenancy.close()
