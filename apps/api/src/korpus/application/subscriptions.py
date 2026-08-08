"""What a payment provider tells us, and what we are willing to believe from it.

A webhook is an unauthenticated HTTP request until proven otherwise, and even once its
signature checks out it is a *claim* about a subscription, not the subscription. Five
things happen to every event, in this order, and each one can end it:

  1. verify      the signature covers the raw bytes. Unsigned or mis-signed: rejected,
                 recorded, no state change.
  2. identify    `(provider, provider_event_id)`. Already present: duplicate, and the
                 answer is the answer the first delivery got.
  3. locate      the subscription it refers to. Unknown: rejected — inventing one from a
                 webhook is how a forged event creates a paid customer.
  4. adjudicate  is this transition in `ALLOWED_SUBSCRIPTION_TRANSITIONS`, and is this
                 event newer than what we already applied. Neither: rejected.
  5. apply       the event row, the subscription move and the audit event in one commit.

Every outcome is recorded, including the refusals. An event that was rejected and left no
trace is indistinguishable from one that never arrived, and the difference between those
two is the whole of a billing dispute.

The direction of trust never reverses: no branch here reads a status out of a payload and
writes it to the subscription. It reads a *requested* status and asks the lifecycle
whether the subscription may go there.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from korpus.application.tenancy_ports import (
    AccountStore,
    BillingEventRejected,
    BillingProvider,
    InvalidSubscriptionTransition,
    PlanNotFound,
    SubscriptionStore,
)
from korpus.domain.tenancy import (
    ALLOWED_SUBSCRIPTION_TRANSITIONS,
    BillingEventRecord,
    BillingEventResult,
    SubscriptionRecord,
    SubscriptionStatus,
)

#: A body larger than this is refused before it is parsed. A webhook describing one
#: subscription has no legitimate reason to be large, and "parse first, judge later" is how
#: an endpoint that requires no authentication to reach becomes a memory exhaustion.
MAX_PAYLOAD_BYTES = 64 * 1024


class SubscriptionService:
    def __init__(
        self,
        subscriptions: SubscriptionStore,
        accounts: AccountStore,
        provider: BillingProvider,
    ) -> None:
        self._subscriptions = subscriptions
        self._accounts = accounts
        self._provider = provider

    # ------------------------------------------------------------ commercial

    def start_subscription(
        self, actor_subject: str, account_id: UUID, plan_code: str
    ) -> SubscriptionRecord:
        """Create an INCOMPLETE subscription. It pays for nothing until an event says so.

        Starting is not paying, and this method deliberately cannot produce an ACTIVE
        subscription. The only path to ACTIVE is a verified provider event, which means a
        bug in checkout — or a request forged against this endpoint — cannot hand anybody
        a paid entitlement.
        """
        if self._accounts.get_account(account_id) is None:
            raise BillingEventRejected(f"unknown account {account_id}")
        plan = self._subscriptions.get_plan_by_code(plan_code)
        if plan is None:
            raise PlanNotFound(plan_code)
        subscription = SubscriptionRecord(
            account_id=account_id,
            plan_id=plan.id,
            provider=self._provider.name,
            status=SubscriptionStatus.INCOMPLETE,
        )
        return self._subscriptions.create_subscription(actor_subject, subscription)

    def active_subscription(
        self, account_id: UUID, *, now: datetime | None = None
    ) -> SubscriptionRecord | None:
        moment = now or datetime.now(UTC)
        for subscription in self._subscriptions.list_subscriptions(account_id):
            if subscription.active_at(moment):
                return subscription
        return None

    # --------------------------------------------------------------- webhook

    def handle_event(
        self, payload: bytes, signature: str | None, *, now: datetime | None = None
    ) -> BillingEventResult:
        """Verify, identify, locate, adjudicate, apply. Any step may end it."""
        moment = now or datetime.now(UTC)
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise BillingEventRejected("payload exceeds the accepted size")

        try:
            event = self._provider.verify_event(payload, signature)
            provider_event_id, event_type = self._provider.event_identity(event)
            view = self._provider.subscription_view(event)
        except (ValueError, KeyError, TypeError) as error:
            # Malformed or unauthenticated. Nothing is recorded against a subscription
            # because nothing here identifies one: an event we cannot parse cannot be
            # attributed, and attributing it to a guess is worse than dropping it.
            raise BillingEventRejected(f"unverifiable event: {type(error).__name__}") from error

        digest = hashlib.sha256(payload).hexdigest()
        existing = self._subscriptions.get_billing_event(self._provider.name, provider_event_id)
        if existing is not None:
            # Idempotent by identity, not by content. A provider redelivering the same
            # event id with a different body is a provider bug or an attack, and neither
            # gets a second adjudication.
            #
            # `DUPLICATE` rather than the first delivery's outcome, which is what this
            # returned until a test asked for the difference: the caller needs to know
            # that nothing happened *this time*, and a redelivery answering `APPLIED`
            # makes a retry storm look like a hundred successful activations in the
            # metrics. What the first delivery decided is still on the stored row.
            return BillingEventResult.DUPLICATE

        record = BillingEventRecord(
            provider=self._provider.name,
            provider_event_id=provider_event_id,
            event_type=event_type,
            payload_hash=digest,
            received_at=moment,
        )
        return self._apply(record, view, moment)

    def _apply(
        self, record: BillingEventRecord, view: dict[str, Any], moment: datetime
    ) -> BillingEventResult:
        provider_subscription_id = str(view.get("provider_subscription_id") or "")
        subscription = (
            self._subscriptions.find_subscription_by_provider_id(
                self._provider.name, provider_subscription_id
            )
            if provider_subscription_id
            else None
        )
        if subscription is None:
            subscription = self._link_pending(view)

        if subscription is None:
            return self._reject(
                record,
                None,
                "the event names a subscription this system has never created",
            )

        try:
            requested = SubscriptionStatus(str(view.get("status")))
        except ValueError:
            return self._reject(record, subscription, "the event names no known status")

        occurred_at = view.get("occurred_at")
        occurred = None
        if isinstance(occurred_at, datetime):
            occurred = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
            # Compared against the last APPLIED event's provider timestamp, not the
            # subscription's `updated_at`: `updated_at` is our processing clock, and a
            # legitimate in-order event almost always carries an `occurred_at` earlier than
            # when we handle it, so comparing against it rejected valid deliveries and
            # jammed the subscription. None means nothing has applied yet — accept.
            if subscription.last_event_at is not None and occurred < subscription.last_event_at:
                # A genuinely older event than the one we last applied. Applying it would
                # move the subscription backwards — a canceled subscription resurrected by
                # replaying the invoice that once made it active.
                return self._reject(
                    record, subscription, "the event predates the last applied event"
                )

        allowed = ALLOWED_SUBSCRIPTION_TRANSITIONS[subscription.status]
        if requested not in allowed:
            self._reject(
                record,
                subscription,
                f"transition {subscription.status.value} -> {requested.value} is not permitted",
            )
            raise InvalidSubscriptionTransition(subscription.status, requested)

        return self._subscriptions.record_billing_event(
            record,
            subscription_id=subscription.id,
            result=BillingEventResult.APPLIED,
            applied_status=requested,
            period_start=_as_datetime(view.get("current_period_start")),
            period_end=_as_datetime(view.get("current_period_end")),
            cancel_at_period_end=(
                bool(view["cancel_at_period_end"]) if "cancel_at_period_end" in view else None
            ),
            event_occurred_at=occurred,
            provider_subscription_id=(
                provider_subscription_id
                if provider_subscription_id and not subscription.provider_subscription_id
                else None
            ),
            audit_payload={
                "provider": record.provider,
                "provider_event_id": record.provider_event_id,
                "event_type": record.event_type,
                "payload_sha256": record.payload_hash,
                "subscription_id": str(subscription.id),
                "previous_status": subscription.status.value,
                "status": requested.value,
                "interpretation": (
                    "A verified provider event moved a subscription along a permitted "
                    "transition. The payload is recorded as a hash, never as a body: it "
                    "carries customer and card metadata, and the only question it has to "
                    "answer here is whether this exact event has been seen before."
                ),
            },
        )

    def _link_pending(self, view: dict[str, Any]) -> SubscriptionRecord | None:
        """Attach a provider subscription id to the row checkout created.

        The first event for a subscription is the one that tells us what the provider
        calls it. It is matched by the id *we* generated and sent as metadata, never by
        account or email: matching on those would let an event naming somebody else's
        address activate their subscription.
        """
        reference = view.get("subscription_reference")
        if not isinstance(reference, str) or not reference:
            return None
        try:
            subscription_id = UUID(reference)
        except ValueError:
            return None
        return self._subscriptions.get_subscription(subscription_id)

    def _reject(
        self,
        record: BillingEventRecord,
        subscription: SubscriptionRecord | None,
        detail: str,
    ) -> BillingEventResult:
        """Record the refusal and change nothing.

        Recorded rather than dropped: a rejected event that left no trace is
        indistinguishable from one that never arrived, and telling those apart is the
        whole of a billing dispute. Storing it also consumes the idempotency key, so a
        redelivery of the same bad event is answered as a duplicate instead of being
        re-adjudicated.
        """
        self._subscriptions.record_billing_event(
            record,
            subscription_id=subscription.id if subscription else None,
            result=BillingEventResult.REJECTED,
            applied_status=None,
            period_start=None,
            period_end=None,
            cancel_at_period_end=None,
            audit_payload={
                "provider": record.provider,
                "provider_event_id": record.provider_event_id,
                "event_type": record.event_type,
                "payload_sha256": record.payload_hash,
                "subscription_id": str(subscription.id) if subscription else None,
                "detail": detail,
                "interpretation": (
                    "The event was recorded and not applied. No subscription changed "
                    "state. A refusal that left no trace could not be distinguished later "
                    "from an event that never arrived."
                ),
            },
        )
        return BillingEventResult.REJECTED


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None
