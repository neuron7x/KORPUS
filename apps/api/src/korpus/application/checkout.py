"""Provider-neutral checkout without moving payment authority into the browser.

The browser may receive a provider POST form, but it never decides the amount, currency,
plan, account or subscription state. Those values come from the persisted plan and the
account derived from authentication. Starting checkout creates an INCOMPLETE subscription;
only a verified callback may activate it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from korpus.application.subscriptions import SubscriptionService
from korpus.application.tenancy_ports import (
    AccountStore,
    CheckoutUnavailable,
    PlanNotFound,
    SubscriptionStore,
)
from korpus.domain.tenancy import AccountRecord, PlanRecord, SubscriptionRecord


@dataclass(frozen=True, slots=True)
class CheckoutDescriptor:
    subscription_id: UUID
    provider: str
    action_url: str
    method: str
    fields: dict[str, str]


class CheckoutProvider(Protocol):
    name: str

    def create_checkout(
        self,
        *,
        account: AccountRecord,
        subscription: SubscriptionRecord,
        plan: PlanRecord,
        callback_url: str,
        result_url: str,
    ) -> CheckoutDescriptor: ...


class CheckoutService:
    def __init__(
        self,
        accounts: AccountStore,
        subscriptions: SubscriptionStore,
        subscription_service: SubscriptionService,
        provider: CheckoutProvider,
        public_base_url: str,
    ) -> None:
        self._accounts = accounts
        self._subscriptions = subscriptions
        self._subscription_service = subscription_service
        self._provider = provider
        self._base = public_base_url.rstrip("/")

    def start(self, actor_subject: str, account_id: UUID, plan_code: str) -> CheckoutDescriptor:
        account = self._accounts.get_account(account_id)
        if account is None:
            raise CheckoutUnavailable("account does not exist")
        if self._subscription_service.active_subscription(account_id) is not None:
            raise CheckoutUnavailable("account already has an active subscription")
        plan = self._subscriptions.get_plan_by_code(plan_code)
        if plan is None:
            raise PlanNotFound(plan_code)
        if plan.price_minor is None or plan.currency is None:
            raise CheckoutUnavailable("plan has no configured sellable price")
        if not self._base:
            raise CheckoutUnavailable("billing public base URL is not configured")
        subscription = self._subscription_service.start_subscription(
            actor_subject, account_id, plan_code
        )
        return self._provider.create_checkout(
            account=account,
            subscription=subscription,
            plan=plan,
            callback_url=f"{self._base}/v1/billing/liqpay/callback",
            result_url=f"{self._base}/?billing=return",
        )
