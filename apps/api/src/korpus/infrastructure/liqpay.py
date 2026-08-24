"""LiqPay client-server subscription adapter.

KORPUS never receives card number or CVV. The browser POSTs a server-generated ``data``
and ``signature`` pair to LiqPay Checkout with ``action=subscribe``; LiqPay later POSTs a
signed callback to KORPUS. The callback signature is verified over the exact base64 ``data``
string before any order id, amount or status is believed.

The public documentation currently specifies SHA3-256 for the signature formula while
legacy snippets on the same documentation still show SHA-1. The algorithm is therefore an
explicit deployment setting, never an "accept either" fallback: accepting two algorithms
would quietly keep the weaker one alive after an operator thought it had been removed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from korpus.application.checkout import CheckoutDescriptor
from korpus.application.tenancy_ports import BillingEventIgnored
from korpus.infrastructure.liqpay_math import amount_minor, provider_datetime
from korpus.domain.tenancy import (
    AccountRecord,
    BillingInterval,
    MAX_PLAN_PRICE_MINOR,
    PlanRecord,
    SubscriptionRecord,
)

CHECKOUT_URL = "https://www.liqpay.ua/api/3/checkout"
_FINAL = frozenset({"error", "failure", "reversed", "subscribed", "success", "unsubscribed"})


class LiqPayBillingProvider:
    name = "liqpay"

    def __init__(
        self,
        public_key: str,
        private_key: str,
        *,
        signature_algorithm: str = "sha3_256",
    ) -> None:
        if not public_key.strip() or not private_key.strip():
            raise ValueError("LiqPay public and private keys are required")
        if signature_algorithm not in {"sha3_256", "sha1"}:
            raise ValueError("unsupported LiqPay signature algorithm")
        self.public_key = public_key.strip()
        self._private_key = private_key.strip()
        self._algorithm = signature_algorithm

    def _digest(self, value: bytes) -> bytes:
        if self._algorithm == "sha3_256":
            return hashlib.sha3_256(value).digest()
        return hashlib.sha1(value, usedforsecurity=False).digest()

    def sign_data(self, data: str) -> str:
        material = f"{self._private_key}{data}{self._private_key}".encode("utf-8")
        return base64.b64encode(self._digest(material)).decode("ascii")

    def create_checkout(
        self,
        *,
        account: AccountRecord,
        subscription: SubscriptionRecord,
        plan: PlanRecord,
        callback_url: str,
        result_url: str,
    ) -> CheckoutDescriptor:
        if plan.price_minor is None or plan.currency is None:
            raise ValueError("plan is not sellable")
        periodicity = {
            BillingInterval.MONTHLY: "month",
            BillingInterval.YEARLY: "year",
        }[plan.billing_interval]
        now = datetime.now(UTC)
        body: dict[str, Any] = {
            "version": 7,
            "public_key": self.public_key,
            "action": "subscribe",
            "amount": _minor_to_decimal(plan.price_minor),
            "currency": plan.currency,
            "description": f"KORPUS · {plan.name}",
            # This is our immutable subscription reference. A callback names the row we
            # created before redirect; it cannot create a row by naming an email/account.
            "order_id": str(subscription.id),
            "customer": str(account.id),
            "subscribe": "1",
            "subscribe_date_start": now.strftime("%Y-%m-%d %H:%M:%S"),
            "subscribe_periodicity": periodicity,
            "server_url": callback_url,
            "result_url": result_url,
            "language": "uk",
        }
        encoded = base64.b64encode(
            json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        return CheckoutDescriptor(
            subscription_id=subscription.id,
            provider=self.name,
            action_url=CHECKOUT_URL,
            method="POST",
            fields={"data": encoded, "signature": self.sign_data(encoded)},
        )

    def verify_event(self, payload: bytes, signature: str | None) -> dict[str, Any]:
        if not signature:
            raise ValueError("unsigned LiqPay callback")
        try:
            data = payload.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("LiqPay data is not ASCII base64") from exc
        expected = self.sign_data(data)
        if not hmac.compare_digest(expected, signature.strip()):
            raise ValueError("LiqPay callback signature does not match")
        try:
            decoded = base64.b64decode(data, validate=True)
            event = json.loads(decoded.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("LiqPay callback data is malformed") from exc
        if not isinstance(event, dict):
            raise ValueError("LiqPay callback data is not an object")
        if str(event.get("public_key") or "") != self.public_key:
            raise ValueError("LiqPay callback names another merchant")
        return event

    def event_identity(self, event: dict[str, Any]) -> tuple[str, str]:
        action = str(event.get("action") or "").strip().lower()
        status = str(event.get("status") or "").strip().lower()
        transaction = next(
            (
                str(event[key]).strip()
                for key in ("transaction_id", "payment_id", "liqpay_order_id")
                if event.get(key) not in (None, "")
            ),
            "",
        )
        if not action or not status or not transaction:
            raise ValueError("LiqPay callback carries no stable transaction identity")
        # Status is part of identity: providers can legitimately update one transaction
        # from a pending to a terminal state. Retries of the same terminal callback remain
        # duplicates, while a later state is adjudicated once.
        return f"{transaction}:{action}:{status}", f"{action}.{status}"

    def subscription_view(self, event: dict[str, Any]) -> dict[str, Any]:
        status = str(event.get("status") or "").strip().lower()
        action = str(event.get("action") or "").strip().lower()
        if status not in _FINAL:
            raise BillingEventIgnored(f"non-final LiqPay status: {status or 'missing'}")

        mapped = _mapped_status(action, status)

        reference = str(event.get("order_id") or "").strip()
        if not reference:
            raise ValueError("LiqPay callback has no order_id")
        return {
            "status": mapped,
            "provider_subscription_id": None,
            "subscription_reference": reference,
            "current_period_start": None,
            "current_period_end": None,
            "cancel_at_period_end": False,
            "occurred_at": _provider_datetime(
                event.get("end_date") or event.get("completion_date") or event.get("create_date")
            ),
            "amount_minor": _amount_minor(event.get("amount")),
            "currency": str(event.get("currency") or "").strip().upper() or None,
            "requires_period_bound": mapped == "active",
        }


def _mapped_status(action: str, status: str) -> str:
    mapping = {
        ("subscribe", "subscribed"): "active",
        ("subscribe", "success"): "active",
        ("regular", "subscribed"): "active",
        ("regular", "success"): "active",
        ("regular", "failure"): "past_due",
        ("regular", "error"): "past_due",
        ("subscribe", "failure"): "expired",
        ("subscribe", "error"): "expired",
    }
    if status in {"unsubscribed", "reversed"}:
        return "canceled"
    try:
        return mapping[(action, status)]
    except KeyError as exc:
        raise ValueError(f"unsupported LiqPay terminal state: {action}/{status}") from exc


def _minor_to_decimal(minor: int) -> str:
    return f"{minor // 100}.{minor % 100:02d}"


def _amount_minor(value: Any) -> int | None:
    return amount_minor(value, MAX_PLAN_PRICE_MINOR)


def _provider_datetime(value: Any) -> datetime | None:
    return provider_datetime(value)
