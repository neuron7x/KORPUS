"""Adjudicate an authenticated provider claim against KORPUS subscription state."""
from __future__ import annotations

import calendar
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from korpus.application.tenancy_ports import InvalidSubscriptionTransition, SubscriptionStore
from korpus.domain.tenancy import (
    ALLOWED_SUBSCRIPTION_TRANSITIONS,
    BillingEventRecord,
    BillingEventResult,
    BillingInterval,
    SubscriptionRecord,
    SubscriptionStatus,
)


class BillingEventAdjudicator:
    def __init__(self, subscriptions: SubscriptionStore, provider_name: str) -> None:
        self._subscriptions = subscriptions
        self._provider_name = provider_name

    def apply(
        self, record: BillingEventRecord, view: dict[str, Any], moment: datetime
    ) -> BillingEventResult:
        subscription, provider_id = self._resolve_subscription(view)
        if subscription is None:
            return self._reject(record, None, "the event names a subscription this system has never created")
        requested = self._requested_status(record, subscription, view)
        if requested is None:
            return BillingEventResult.REJECTED
        occurred = self._occurred_at(record, subscription, view)
        if occurred is False:
            return BillingEventResult.REJECTED
        plan = self._subscriptions.get_plan(subscription.plan_id)
        if plan is None:
            return self._reject(record, subscription, "subscription plan no longer exists")
        if not self._terms_match(plan.price_minor, plan.currency, requested, view):
            return self._reject(record, subscription, "provider amount/currency does not match plan")
        self._require_transition(record, subscription, requested)
        start, end = self._period_bounds(view, requested, occurred, moment, plan.billing_interval)
        return self._record_applied(
            record, subscription, requested, view, occurred, start, end, provider_id
        )

    def _resolve_subscription(
        self, view: dict[str, Any]
    ) -> tuple[SubscriptionRecord | None, str]:
        provider_id = str(view.get("provider_subscription_id") or "")
        subscription = (
            self._subscriptions.find_subscription_by_provider_id(self._provider_name, provider_id)
            if provider_id
            else None
        )
        if subscription is not None:
            return subscription, provider_id
        reference = view.get("subscription_reference")
        if not isinstance(reference, str) or not reference:
            return None, provider_id
        try:
            return self._subscriptions.get_subscription(UUID(reference)), provider_id
        except ValueError:
            return None, provider_id

    def _requested_status(
        self, record: BillingEventRecord, subscription: SubscriptionRecord, view: dict[str, Any]
    ) -> SubscriptionStatus | None:
        try:
            return SubscriptionStatus(str(view.get("status")))
        except ValueError:
            self._reject(record, subscription, "the event names no known status")
            return None

    def _occurred_at(
        self, record: BillingEventRecord, subscription: SubscriptionRecord, view: dict[str, Any]
    ) -> datetime | None | bool:
        value = view.get("occurred_at")
        if not isinstance(value, datetime):
            return None
        occurred = value if value.tzinfo else value.replace(tzinfo=UTC)
        if subscription.last_event_at is not None and occurred < subscription.last_event_at:
            self._reject(record, subscription, "the event predates the last applied event")
            return False
        return occurred

    @staticmethod
    def _terms_match(
        price_minor: int | None,
        currency: str | None,
        requested: SubscriptionStatus,
        view: dict[str, Any],
    ) -> bool:
        if requested is not SubscriptionStatus.ACTIVE or price_minor is None:
            return True
        return view.get("amount_minor") == price_minor and view.get("currency") == currency

    def _require_transition(
        self,
        record: BillingEventRecord,
        subscription: SubscriptionRecord,
        requested: SubscriptionStatus,
    ) -> None:
        if requested in ALLOWED_SUBSCRIPTION_TRANSITIONS[subscription.status]:
            return
        self._reject(
            record,
            subscription,
            f"transition {subscription.status.value} -> {requested.value} is not permitted",
        )
        raise InvalidSubscriptionTransition(subscription.status, requested)

    @staticmethod
    def _period_bounds(
        view: dict[str, Any],
        requested: SubscriptionStatus,
        occurred: datetime | None | bool,
        moment: datetime,
        interval: BillingInterval,
    ) -> tuple[datetime | None, datetime | None]:
        start = _as_datetime(view.get("current_period_start"))
        end = _as_datetime(view.get("current_period_end"))
        if requested is SubscriptionStatus.ACTIVE and view.get("requires_period_bound"):
            start = start or (occurred if isinstance(occurred, datetime) else None) or moment
            end = end or _period_end(start, interval)
        return start, end

    def _record_applied(
        self,
        record: BillingEventRecord,
        subscription: SubscriptionRecord,
        requested: SubscriptionStatus,
        view: dict[str, Any],
        occurred: datetime | None | bool,
        period_start: datetime | None,
        period_end: datetime | None,
        provider_id: str,
    ) -> BillingEventResult:
        return self._subscriptions.record_billing_event(
            record,
            subscription_id=subscription.id,
            result=BillingEventResult.APPLIED,
            applied_status=requested,
            period_start=period_start,
            period_end=period_end,
            cancel_at_period_end=(
                bool(view["cancel_at_period_end"]) if "cancel_at_period_end" in view else None
            ),
            event_occurred_at=occurred if isinstance(occurred, datetime) else None,
            provider_subscription_id=(
                provider_id if provider_id and not subscription.provider_subscription_id else None
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
                    "A verified provider event moved a subscription along a permitted transition. "
                    "The payload is retained only as a hash, never as raw payment metadata."
                ),
            },
        )

    def _reject(
        self,
        record: BillingEventRecord,
        subscription: SubscriptionRecord | None,
        detail: str,
    ) -> BillingEventResult:
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
                "interpretation": "The event was recorded and not applied; subscription state did not change.",
            },
        )
        return BillingEventResult.REJECTED


def _period_end(start: datetime, interval: BillingInterval) -> datetime:
    if interval is BillingInterval.YEARLY:
        year = start.year + 1
        day = min(start.day, calendar.monthrange(year, start.month)[1])
        return start.replace(year=year, day=day)
    month_index = start.month
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
