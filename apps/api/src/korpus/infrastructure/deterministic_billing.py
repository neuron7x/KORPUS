"""A billing provider with no vendor behind it.

There is no payment processor account for this system, and inventing one would mean
committing credentials that do not exist and a signature scheme nobody has verified
against the real thing. What exists instead is a provider that is *real in every respect
that the rest of the code can observe*: it authenticates a webhook with an HMAC over the
raw bytes, it names events, and it refuses everything malformed — so the transition rules,
the idempotency key and the audit trail are exercised by the same code path a vendor
adapter would use.

What it deliberately does not do is charge anybody. `SUP-BILLING-001` in the debt register
records the remaining external work: an adapter for a chosen processor, its signature
scheme, and its event vocabulary mapped onto `SubscriptionStatus`. That work is a
translation layer on top of this interface, not a change to it.

The signature covers the bytes as received. Re-serialising parsed JSON and hashing that is
the single most common way a webhook verifier is written wrong: it passes every test where
the test built the payload with the same serialiser, and fails against a provider whose key
order differs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

#: Vocabulary the deterministic provider speaks, mapped onto the domain's lifecycle. A
#: vendor adapter provides its own table; the point is that one exists and is explicit,
#: rather than a status string travelling from a payload into a column.
EVENT_STATUS = {
    "subscription.activated": "active",
    "subscription.renewed": "active",
    "subscription.payment_failed": "past_due",
    "subscription.canceled": "canceled",
    "subscription.expired": "expired",
}


class DeterministicBillingProvider:
    """HMAC-authenticated webhooks with no vendor. See the module docstring."""

    name = "deterministic"

    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            # Short enough to brute-force is short enough to forge an activation with.
            raise ValueError("billing webhook secret must be at least 32 characters")
        self._secret = secret.encode("utf-8")

    def sign(self, payload: bytes) -> str:
        """Used by the tests and the drills to produce a genuine signature."""
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def verify_event(self, payload: bytes, signature: str | None) -> dict[str, Any]:
        if not signature:
            raise ValueError("unsigned billing event")
        expected = self.sign(payload)
        if not hmac.compare_digest(expected, signature.strip().lower()):
            # Constant-time. A comparison that returns early leaks the prefix, and a
            # signature is exactly the kind of secret that can be recovered a byte at a
            # time by an endpoint that answers quickly when the first byte is wrong.
            raise ValueError("billing event signature does not match")
        body = json.loads(payload.decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("billing event is not an object")
        return body

    def event_identity(self, event: dict[str, Any]) -> tuple[str, str]:
        event_id = str(event.get("id") or "").strip()
        event_type = str(event.get("type") or "").strip()
        if not event_id or not event_type:
            raise ValueError("billing event carries no id or type")
        return event_id, event_type

    def subscription_view(self, event: dict[str, Any]) -> dict[str, Any]:
        data = event.get("data")
        if not isinstance(data, dict):
            raise ValueError("billing event carries no subscription data")
        event_type = str(event.get("type") or "")
        status = EVENT_STATUS.get(event_type)
        if status is None:
            raise ValueError(f"unmapped billing event type: {event_type}")
        return {
            "status": status,
            "provider_subscription_id": data.get("subscription_id"),
            "subscription_reference": data.get("reference"),
            "current_period_start": data.get("period_start"),
            "current_period_end": data.get("period_end"),
            "cancel_at_period_end": data.get("cancel_at_period_end", False),
            "occurred_at": _timestamp(event.get("occurred_at")),
        }


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None
