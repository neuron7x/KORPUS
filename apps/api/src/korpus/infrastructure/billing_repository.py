"""Plans, subscriptions and billing events in SQL.

The whole of this file exists to make one sentence true: *an event either changed the
subscription and was recorded, or did neither.*

Everything else follows from it. The event row and the subscription update are in one
commit, so a crash between them is not a state where the idempotency key says an event was
handled and the subscription disagrees — a state that is unrecoverable in practice,
because the provider's redelivery is now a duplicate and the only fix is a human comparing
two systems by hand.

Duplicate detection is the unique constraint, not a `SELECT` before an `INSERT`. Providers
redeliver: on timeout, on 5xx, on their own retry schedule, and often within milliseconds.
The pre-read here is an optimisation that answers the common case cheaply; the constraint
is what makes it correct when two deliveries arrive at once.

What this file does not do is decide whether a transition is legal. That is
`ALLOWED_SUBSCRIPTION_TRANSITIONS` in the domain, applied by the service — a storage layer
that also adjudicated would be the only place the rule lived, and it would be reachable
only through a database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from korpus.domain.tenancy import (
    BillingEventRecord,
    BillingEventResult,
    BillingInterval,
    PlanRecord,
    PlanStatus,
    SubscriptionRecord,
    SubscriptionStatus,
)
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.tenancy_repository import aware, system_actor
from korpus.infrastructure.tenancy_schema import billing_events, plans, subscriptions


def _plan(row: Any) -> PlanRecord:
    return PlanRecord(
        id=UUID(row["id"]),
        code=row["code"],
        name=row["name"],
        status=PlanStatus(row["status"]),
        billing_interval=BillingInterval(row["billing_interval"]),
        external_product_reference=row["external_product_reference"],
        external_price_reference=row["external_price_reference"],
        entitled_corpora=frozenset(json.loads(row["entitled_corpora_json"] or "[]")),
        created_at=aware(row["created_at"]),
        updated_at=aware(row["updated_at"]),
    )


def _subscription(row: Any) -> SubscriptionRecord:
    return SubscriptionRecord(
        id=UUID(row["id"]),
        account_id=UUID(row["account_id"]),
        plan_id=UUID(row["plan_id"]),
        provider=row["provider"],
        provider_customer_id=row["provider_customer_id"],
        provider_subscription_id=row["provider_subscription_id"],
        status=SubscriptionStatus(row["status"]),
        current_period_start=aware(row["current_period_start"]),
        current_period_end=aware(row["current_period_end"]),
        cancel_at_period_end=bool(row["cancel_at_period_end"]),
        created_at=aware(row["created_at"]),
        updated_at=aware(row["updated_at"]),
    )


def _billing_event(row: Any) -> BillingEventRecord:
    return BillingEventRecord(
        id=UUID(row["id"]),
        provider=row["provider"],
        provider_event_id=row["provider_event_id"],
        event_type=row["event_type"],
        payload_hash=row["payload_hash"],
        received_at=aware(row["received_at"]),
        processed_at=aware(row["processed_at"]),
        processing_result=(
            BillingEventResult(row["processing_result"]) if row["processing_result"] else None
        ),
    )


class SqlSubscriptionStore:
    def __init__(self, repository: SqlRepository) -> None:
        self._repository = repository
        self.engine = repository.engine

    # ------------------------------------------------------------------ plans

    def upsert_plan(self, plan: PlanRecord) -> PlanRecord:
        """Insert by code, or update the sellable fields of the plan that has it.

        `entitled_corpora` is one of the updated fields, and that is the one line in this
        file that can widen access. It is why plan writes are an operator action with an
        audit event and not an API endpoint — see `korpus.api.routes_billing`, which
        exposes reads only.
        """
        moment = datetime.now(UTC)

        def operation(connection: Connection) -> tuple[PlanRecord, tuple[int, str]]:
            existing = (
                connection.execute(select(plans).where(plans.c.code == plan.code))
                .mappings()
                .first()
            )
            corpora_json = json.dumps(sorted(plan.entitled_corpora), separators=(",", ":"))
            if existing is None:
                connection.execute(
                    insert(plans).values(
                        id=str(plan.id),
                        code=plan.code,
                        name=plan.name,
                        status=plan.status.value,
                        billing_interval=plan.billing_interval.value,
                        external_product_reference=plan.external_product_reference,
                        external_price_reference=plan.external_price_reference,
                        entitled_corpora_json=corpora_json,
                        created_at=moment,
                        updated_at=moment,
                    )
                )
                stored = plan.model_copy(update={"created_at": moment, "updated_at": moment})
                action = "plan.created"
            else:
                connection.execute(
                    update(plans)
                    .where(plans.c.code == plan.code)
                    .values(
                        name=plan.name,
                        status=plan.status.value,
                        billing_interval=plan.billing_interval.value,
                        external_product_reference=plan.external_product_reference,
                        external_price_reference=plan.external_price_reference,
                        entitled_corpora_json=corpora_json,
                        updated_at=moment,
                    )
                )
                stored = plan.model_copy(
                    update={
                        "id": UUID(existing["id"]),
                        "created_at": aware(existing["created_at"]),
                        "updated_at": moment,
                    }
                )
                action = "plan.updated"
            anchor = self._repository.audit_in_connection(
                connection,
                system_actor("operator"),
                action,
                "plan",
                str(stored.id),
                {
                    "code": plan.code,
                    "status": plan.status.value,
                    "entitled_corpora": sorted(plan.entitled_corpora),
                    "interpretation": (
                        "A plan names which corpora a paid subscription may reach. It can "
                        "only ever narrow what the policy engine already permits: the "
                        "entitlement is intersected with the identity's own corpora, never "
                        "unioned."
                    ),
                },
            )
            return stored, anchor

        return self._repository.audited_transaction(operation)

    def list_plans(self, *, include_retired: bool = False) -> list[PlanRecord]:
        statement = select(plans).order_by(plans.c.code)
        if not include_retired:
            statement = statement.where(plans.c.status == PlanStatus.ACTIVE.value)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [_plan(row) for row in rows]

    def get_plan(self, plan_id: UUID) -> PlanRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(plans).where(plans.c.id == str(plan_id)))
                .mappings()
                .first()
            )
        return _plan(row) if row else None

    def get_plan_by_code(self, code: str) -> PlanRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(plans).where(plans.c.code == code)).mappings().first()
        return _plan(row) if row else None

    # ---------------------------------------------------------- subscriptions

    def create_subscription(
        self, actor_subject: str, subscription: SubscriptionRecord
    ) -> SubscriptionRecord:
        def operation(connection: Connection) -> tuple[SubscriptionRecord, tuple[int, str]]:
            connection.execute(
                insert(subscriptions).values(**self._values(subscription))
            )
            anchor = self._repository.audit_in_connection(
                connection,
                system_actor(actor_subject),
                "subscription.created",
                "subscription",
                str(subscription.id),
                {
                    "account_id": str(subscription.account_id),
                    "plan_id": str(subscription.plan_id),
                    "provider": subscription.provider,
                    "status": subscription.status.value,
                    "interpretation": (
                        "A subscription starts INCOMPLETE and pays for nothing until a "
                        "verified provider event moves it to ACTIVE. Creation is not "
                        "payment."
                    ),
                },
            )
            return subscription, anchor

        return self._repository.audited_transaction(operation)

    def get_subscription(self, subscription_id: UUID) -> SubscriptionRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(subscriptions).where(subscriptions.c.id == str(subscription_id))
                )
                .mappings()
                .first()
            )
        return _subscription(row) if row else None

    def list_subscriptions(self, account_id: UUID) -> list[SubscriptionRecord]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(subscriptions)
                    .where(subscriptions.c.account_id == str(account_id))
                    .order_by(subscriptions.c.created_at.desc(), subscriptions.c.id)
                )
                .mappings()
                .all()
            )
        return [_subscription(row) for row in rows]

    def find_subscription_by_provider_id(
        self, provider: str, provider_subscription_id: str
    ) -> SubscriptionRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(subscriptions)
                    .where(subscriptions.c.provider == provider)
                    .where(
                        subscriptions.c.provider_subscription_id == provider_subscription_id
                    )
                )
                .mappings()
                .first()
            )
        return _subscription(row) if row else None

    # -------------------------------------------------------- billing events

    def get_billing_event(
        self, provider: str, provider_event_id: str
    ) -> BillingEventRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(billing_events)
                    .where(billing_events.c.provider == provider)
                    .where(billing_events.c.provider_event_id == provider_event_id)
                )
                .mappings()
                .first()
            )
        return _billing_event(row) if row else None

    def record_billing_event(
        self,
        event: BillingEventRecord,
        *,
        subscription_id: UUID | None,
        result: BillingEventResult,
        applied_status: SubscriptionStatus | None,
        period_start: datetime | None,
        period_end: datetime | None,
        cancel_at_period_end: bool | None,
        provider_subscription_id: str | None = None,
        audit_payload: dict[str, Any],
    ) -> BillingEventResult:
        """The event row, the subscription move and the audit event, in one commit."""
        moment = datetime.now(UTC)

        def operation(connection: Connection) -> tuple[BillingEventResult, tuple[int, str]]:
            connection.execute(
                insert(billing_events).values(
                    id=str(event.id),
                    provider=event.provider,
                    provider_event_id=event.provider_event_id,
                    event_type=event.event_type,
                    payload_hash=event.payload_hash,
                    received_at=event.received_at,
                    processed_at=moment,
                    processing_result=result.value,
                    subscription_id=str(subscription_id) if subscription_id else None,
                )
            )
            if result is BillingEventResult.APPLIED and subscription_id is not None:
                values: dict[str, Any] = {"updated_at": moment}
                if applied_status is not None:
                    values["status"] = applied_status.value
                if period_start is not None:
                    values["current_period_start"] = period_start
                if period_end is not None:
                    values["current_period_end"] = period_end
                if cancel_at_period_end is not None:
                    values["cancel_at_period_end"] = cancel_at_period_end
                if provider_subscription_id:
                    # Written once, on the first event that carries it. Later events
                    # arrive addressed by the provider's own id rather than by the
                    # reference checkout sent, and without this the second event for a
                    # subscription is unlocatable.
                    values["provider_subscription_id"] = provider_subscription_id
                connection.execute(
                    update(subscriptions)
                    .where(subscriptions.c.id == str(subscription_id))
                    .values(**values)
                )
            anchor = self._repository.audit_in_connection(
                connection,
                system_actor(f"billing:{event.provider}"),
                f"billing.event.{result.value}",
                "billing_event",
                str(event.id),
                audit_payload,
            )
            return result, anchor

        try:
            return self._repository.audited_transaction(operation)
        except IntegrityError:
            # The unique constraint on (provider, provider_event_id) fired: another
            # delivery of this same event committed while this one was in flight. The
            # subscription is in the state that delivery left it in, and applying ours on
            # top would be applying the same event twice.
            return BillingEventResult.DUPLICATE

    @staticmethod
    def _values(subscription: SubscriptionRecord) -> dict[str, Any]:
        return {
            "id": str(subscription.id),
            "account_id": str(subscription.account_id),
            "plan_id": str(subscription.plan_id),
            "provider": subscription.provider,
            "provider_customer_id": subscription.provider_customer_id,
            "provider_subscription_id": subscription.provider_subscription_id,
            "status": subscription.status.value,
            "current_period_start": subscription.current_period_start,
            "current_period_end": subscription.current_period_end,
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "created_at": subscription.created_at,
            "updated_at": subscription.updated_at,
        }
