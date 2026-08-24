"""Commercial API dependencies and response contracts, separate from conversation routes."""
from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from korpus.application.checkout import CheckoutService
from korpus.application.subscriptions import SubscriptionService
from korpus.application.tenancy_ports import BillingProvider, SubscriptionStore


def _state(request: Request, name: str) -> Any:
    value = getattr(request.app.state, name, None)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{name.replace('_', ' ')} is not configured in this deployment",
        )
    return value


def get_subscription_store(request: Request) -> SubscriptionStore:
    return _state(request, "subscription_store")


def get_subscription_service(request: Request) -> SubscriptionService:
    return _state(request, "subscription_service")


def get_checkout_service(request: Request) -> CheckoutService:
    return _state(request, "checkout_service")


def get_billing_provider(request: Request) -> BillingProvider:
    return _state(request, "billing_provider")


SubscriptionStoreDependency = Annotated[SubscriptionStore, Depends(get_subscription_store)]
SubscriptionServiceDependency = Annotated[SubscriptionService, Depends(get_subscription_service)]
CheckoutServiceDependency = Annotated[CheckoutService, Depends(get_checkout_service)]
BillingProviderDependency = Annotated[BillingProvider, Depends(get_billing_provider)]


class PlanView(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    name: str
    billing_interval: str
    price_minor: int | None
    currency: str | None
    sellable: bool
    entitled_corpora: list[str]


class SubscriptionView(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    plan_code: str | None
    status: str
    provider: str
    current_period_end: str | None
    cancel_at_period_end: bool


class EntitlementView(BaseModel):
    model_config = ConfigDict(frozen=True)
    entitled_corpora: list[str]
    subscription_status: str | None
    plan_code: str | None
    reason: str
    enforced: bool


class StartSubscription(BaseModel):
    plan_code: str = Field(min_length=1, max_length=64)
