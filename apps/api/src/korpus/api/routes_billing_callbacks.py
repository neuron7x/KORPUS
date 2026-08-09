"""Unauthenticated-at-HTTP billing callbacks, authenticated by provider signature."""
from __future__ import annotations

from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from starlette.concurrency import run_in_threadpool

from korpus.api.billing_dependencies import BillingProviderDependency, SubscriptionServiceDependency
from korpus.application.tenancy_ports import (
    BillingEventIgnored,
    BillingEventRejected,
    InvalidSubscriptionTransition,
)
from korpus.domain.tenancy import BillingEventResult

callback_router = APIRouter()
MAX_WEBHOOK_BYTES = 64 * 1024


async def _bounded_body(request: Request) -> bytes:
    payload = await request.body()
    if len(payload) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="payload too large")
    return payload


def _result_response(result: BillingEventResult) -> Response:
    code = status.HTTP_202_ACCEPTED if result is BillingEventResult.REJECTED else status.HTTP_200_OK
    return Response(status_code=code, content=result.value, media_type="text/plain")


@callback_router.post("/v1/billing/liqpay/callback", include_in_schema=False)
async def liqpay_callback(
    request: Request,
    subscriptions: SubscriptionServiceDependency,
    provider: BillingProviderDependency,
) -> Response:
    payload = await _bounded_body(request)
    if provider.name != "liqpay":
        raise HTTPException(status_code=503, detail="LiqPay billing provider is not configured")
    try:
        form = parse_qs(payload.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
        data, signature = form.get("data", [""])[0], form.get("signature", [""])[0]
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="malformed callback") from exc
    if not data or not signature:
        raise HTTPException(status_code=400, detail="missing callback fields")
    try:
        result = await run_in_threadpool(subscriptions.handle_event, data.encode("ascii"), signature)
    except BillingEventIgnored:
        return Response(status_code=200, content="ignored", media_type="text/plain")
    except InvalidSubscriptionTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BillingEventRejected as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    return Response(status_code=200, content=result.value, media_type="text/plain")


@callback_router.post("/v1/billing/webhook", include_in_schema=False)
async def billing_webhook(
    request: Request,
    subscriptions: SubscriptionServiceDependency,
    signature: Annotated[str | None, Header(alias="X-Korpus-Signature")] = None,
) -> Response:
    payload = await _bounded_body(request)
    try:
        result = await run_in_threadpool(subscriptions.handle_event, payload, signature)
    except BillingEventIgnored:
        return Response(status_code=200, content="ignored", media_type="text/plain")
    except InvalidSubscriptionTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BillingEventRejected as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    return _result_response(result)
