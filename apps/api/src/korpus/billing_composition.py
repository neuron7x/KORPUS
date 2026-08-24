"""Billing-only composition: provider selection, sellable-plan bootstrap and services."""
from __future__ import annotations

from typing import Any

from korpus.application.checkout import CheckoutService
from korpus.application.subscriptions import SubscriptionService
from korpus.application.tenancy_ports import AccountStore
from korpus.config import Settings
from korpus.domain.tenancy import BillingInterval, PlanRecord, PlanStatus
from korpus.infrastructure.billing_repository import SqlSubscriptionStore
from korpus.infrastructure.deterministic_billing import DeterministicBillingProvider
from korpus.infrastructure.liqpay import LiqPayBillingProvider


def _ensure_configured_plan(settings: Settings, store: SqlSubscriptionStore) -> None:
    if not settings.billing_plan_code:
        return
    desired = PlanRecord(
        code=settings.billing_plan_code,
        name=settings.billing_plan_name,
        status=PlanStatus.ACTIVE,
        billing_interval=BillingInterval(settings.billing_plan_interval),
        price_minor=settings.billing_plan_price_minor,
        currency=settings.billing_plan_currency,
        entitled_corpora=settings.billing_plan_corpus_set,
    )
    existing = store.get_plan_by_code(desired.code)
    if existing is not None and _commercial_shape(existing) == _commercial_shape(desired):
        return
    store.upsert_plan(desired)


def _commercial_shape(plan: PlanRecord) -> tuple[object, ...]:
    return (
        plan.name,
        plan.status,
        plan.billing_interval,
        plan.price_minor,
        plan.currency,
        plan.entitled_corpora,
    )


def _provider(settings: Settings) -> Any | None:
    private = settings.resolved_liqpay_private_key
    if settings.liqpay_public_key and private:
        return LiqPayBillingProvider(
            settings.liqpay_public_key,
            private,
            signature_algorithm=settings.liqpay_signature_algorithm,
        )
    secret = settings.resolved_billing_webhook_secret
    return DeterministicBillingProvider(secret) if secret else None


def build_billing(
    settings: Settings,
    accounts: AccountStore,
    subscriptions: SqlSubscriptionStore,
) -> dict[str, Any]:
    _ensure_configured_plan(settings, subscriptions)
    provider = _provider(settings)
    service = SubscriptionService(subscriptions, accounts, provider) if provider else None
    checkout = (
        CheckoutService(
            accounts,
            subscriptions,
            service,
            provider,
            settings.billing_public_base_url,
        )
        if isinstance(provider, LiqPayBillingProvider) and service is not None
        else None
    )
    return {
        "billing_provider": provider,
        "subscription_service": service,
        "checkout_service": checkout,
    }
