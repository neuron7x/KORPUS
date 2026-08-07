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

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from starlette.concurrency import run_in_threadpool

from korpus.api.routes_tenancy import (
    AccountServiceDependency,
    EntitlementDependency,
    EntitlementView,
    IdentityDependency,
    PlanView,
    StartSubscription,
    SubscriptionView,
    account_for,
    get_subscription_service,
    get_subscription_store,
)
from korpus.application.subscriptions import SubscriptionService
from korpus.application.tenancy_ports import (
    BillingEventRejected,
    InvalidSubscriptionTransition,
    PlanNotFound,
    SubscriptionStore,
)
from korpus.domain.tenancy import BillingEventResult

billing_router = APIRouter()

#: A webhook body larger than this never reaches the provider adapter. One subscription
#: does not need more, and an endpoint reachable without authentication must bound what it
#: is willing to read before it reads it.
MAX_WEBHOOK_BYTES = 64 * 1024


@billing_router.get("/v1/plans", response_model=list[PlanView])
def list_plans(
    identity: IdentityDependency,
    service: AccountServiceDependency,
    store: Annotated[SubscriptionStore, Depends(get_subscription_store)],
) -> list[PlanView]:
    account_for(service, identity)
    return [
        PlanView(
            code=plan.code,
            name=plan.name,
            billing_interval=plan.billing_interval.value,
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
    "/v1/subscription", response_model=SubscriptionView, status_code=status.HTTP_201_CREATED
)
def start_subscription(
    body: StartSubscription,
    identity: IdentityDependency,
    service: AccountServiceDependency,
    subscriptions: Annotated[SubscriptionService, Depends(get_subscription_service)],
    store: Annotated[SubscriptionStore, Depends(get_subscription_store)],
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
            subscription.current_period_end.isoformat()
            if subscription.current_period_end
            else None
        ),
        cancel_at_period_end=subscription.cancel_at_period_end,
    )


@billing_router.post("/v1/billing/webhook", include_in_schema=False)
async def billing_webhook(
    request: Request,
    subscriptions: Annotated[SubscriptionService, Depends(get_subscription_service)],
    signature: Annotated[str | None, Header(alias="X-Korpus-Signature")] = None,
) -> Response:
    """A provider event. Unauthenticated by HTTP, authenticated by signature.

    No identity dependency, deliberately: a payment provider holds no account here. What
    it holds is the webhook secret, and the signature over the raw bytes is the whole of
    the authentication. The body is read as bytes for that reason — re-serialising parsed
    JSON changes them, and a verifier that hashes the re-serialised form passes every test
    that built the payload with the same serialiser and fails against the vendor.
    """
    payload = await request.body()
    if len(payload) > MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="payload too large"
        )
    try:
        result = await run_in_threadpool(subscriptions.handle_event, payload, signature)
    except InvalidSubscriptionTransition as refused:
        # 409, not 400: the event is well-formed and authentic, and the subscription is
        # not where the provider believes it is. That is a reconciliation, and a provider
        # that retries on 4xx should not retry this one forever.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(refused)) from refused
    except BillingEventRejected as refused:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=refused.detail
        ) from refused
    # 200 for applied and duplicate alike: a duplicate is a delivery the provider is
    # entitled to consider successful, and answering anything else makes it retry forever.
    code = (
        status.HTTP_202_ACCEPTED
        if result is BillingEventResult.REJECTED
        else status.HTTP_200_OK
    )
    return Response(status_code=code, content=result.value, media_type="text/plain")


