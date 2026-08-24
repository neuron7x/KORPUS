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
from uuid import UUID

from korpus.application.billing_adjudication import BillingEventAdjudicator
from korpus.application.tenancy_ports import (
    AccountStore,
    BillingEventIgnored,
    BillingEventRejected,
    BillingProvider,
    PlanNotFound,
    SubscriptionStore,
)
from korpus.domain.tenancy import (
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
        self._adjudicator = BillingEventAdjudicator(subscriptions, provider.name)

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
        except BillingEventIgnored:
            raise
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
        return self._adjudicator.apply(record, view, moment)
