"""Plans, subscriptions and the provider webhook.

Split from `routes_tenancy.py` because these three do a different job from the account and
conversation routes: they are the commercial edge, and the webhook among them is the only
endpoint in this system that serves an unauthenticated caller. That is worth having its
own file rather than sitting eleven lines below the conversation list.

The shared pieces — how an account is resolved, how a disabled one is refused — are
imported from `routes_tenancy` rather than duplicated. Two copies of `account_for` is two
places for the refusal to stop being made.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from korpus.api.billing_dependencies import (
    CheckoutServiceDependency,
    EntitlementView,
    PlanView,
    StartSubscription,
    SubscriptionServiceDependency,
    SubscriptionStoreDependency,
    SubscriptionView,
)
from korpus.api.routes_billing_callbacks import callback_router
from korpus.api.routes_tenancy import (
    AccountServiceDependency,
    EntitlementDependency,
    IdentityDependency,
    account_for,
)
from korpus.application.tenancy_ports import (
    BillingEventRejected,
    CheckoutUnavailable,
    PlanNotFound,
)

billing_router = APIRouter()


class CheckoutView(BaseModel):
    model_config = ConfigDict(frozen=True)

    subscription_id: str
    provider: str
    action_url: str
    method: str
    fields: dict[str, str]


@billing_router.get("/v1/plans", response_model=list[PlanView])
def list_plans(
    identity: IdentityDependency,
    service: AccountServiceDependency,
    store: SubscriptionStoreDependency,
) -> list[PlanView]:
    account_for(service, identity)
    return [
        PlanView(
            code=plan.code,
            name=plan.name,
            billing_interval=plan.billing_interval.value,
            price_minor=plan.price_minor,
            currency=plan.currency,
            sellable=plan.price_minor is not None and plan.currency is not None,
            entitled_corpora=sorted(plan.entitled_corpora),
        )
        for plan in store.list_plans()
    ]


@billing_router.get("/v1/subscription", response_model=EntitlementView)
def read_entitlement(
    identity: IdentityDependency,
    service: AccountServiceDependency,
    entitlements: EntitlementDependency,
) -> EntitlementView:
    account = account_for(service, identity)
    entitlement = entitlements.project(account)
    return EntitlementView(
        entitled_corpora=sorted(entitlement.entitled_corpora),
        subscription_status=(
            entitlement.subscription_status.value if entitlement.subscription_status else None
        ),
        plan_code=entitlement.plan_code,
        reason=entitlement.reason,
        enforced=entitlements.enforced,
    )


@billing_router.post(
    "/v1/billing/checkout", response_model=CheckoutView, status_code=status.HTTP_201_CREATED
)
def start_checkout(
    body: StartSubscription,
    identity: IdentityDependency,
    accounts: AccountServiceDependency,
    checkout: CheckoutServiceDependency,
) -> CheckoutView:
    account = account_for(accounts, identity)
    try:
        descriptor = checkout.start(identity.subject, account.id, body.plan_code)
    except PlanNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown plan: {body.plan_code}"
        ) from missing
    except CheckoutUnavailable as refused:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": refused.reason, "detail": refused.detail},
        ) from refused
    return CheckoutView(
        subscription_id=str(descriptor.subscription_id),
        provider=descriptor.provider,
        action_url=descriptor.action_url,
        method=descriptor.method,
        fields=descriptor.fields,
    )


@billing_router.post(
    "/v1/subscription", response_model=SubscriptionView, status_code=status.HTTP_201_CREATED
)
def start_subscription(
    body: StartSubscription,
    identity: IdentityDependency,
    service: AccountServiceDependency,
    subscriptions: SubscriptionServiceDependency,
    store: SubscriptionStoreDependency,
) -> SubscriptionView:
    """Create an INCOMPLETE subscription. It pays for nothing until an event says so.

    This endpoint cannot produce an ACTIVE subscription — not with any body, not by any
    parameter. The only path to ACTIVE is a signed provider event, so a request forged
    against this route buys nothing.
    """
    account = account_for(service, identity)
    try:
        subscription = subscriptions.start_subscription(
            identity.subject, account.id, body.plan_code
        )
    except PlanNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown plan: {body.plan_code}"
        ) from missing
    except BillingEventRejected as refused:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(refused)
        ) from refused
    plan = store.get_plan(subscription.plan_id)
    return SubscriptionView(
        id=subscription.id,
        plan_code=plan.code if plan else None,
        status=subscription.status.value,
        provider=subscription.provider,
        current_period_end=(
            subscription.current_period_end.isoformat() if subscription.current_period_end else None
        ),
        cancel_at_period_end=subscription.cancel_at_period_end,
    )


billing_router.include_router(callback_router)
