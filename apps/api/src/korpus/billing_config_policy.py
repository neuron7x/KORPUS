"""Cross-field validation for payment-provider and sellable-plan configuration."""
from __future__ import annotations
from typing import Any

from korpus.security.url_policy import is_https_or_loopback_origin


def validate_billing_settings(settings: Any) -> None:
    liqpay_configured = bool(settings.liqpay_public_key or settings.resolved_liqpay_private_key)
    if liqpay_configured:
        _validate_liqpay(settings)
    if settings.billing_plan_code:
        _validate_plan(settings)


def _validate_liqpay(settings: Any) -> None:
    if not settings.liqpay_public_key or not settings.resolved_liqpay_private_key:
        raise ValueError("LiqPay checkout requires both public and private keys")
    if settings.liqpay_signature_algorithm not in {"sha3_256", "sha1"}:
        raise ValueError("LiqPay signature algorithm must be sha3_256 or sha1")
    base = settings.billing_public_base_url.rstrip("/")
    if not base or not is_https_or_loopback_origin(base):
        raise ValueError(
            "LiqPay checkout requires an HTTPS billing_public_base_url "
            "or an explicit loopback test origin"
        )


def _validate_plan(settings: Any) -> None:
    if settings.billing_plan_price_minor is None:
        raise ValueError("configured billing plan requires billing_plan_price_minor")
    if settings.billing_plan_currency not in {"UAH", "USD", "EUR"}:
        raise ValueError("configured billing plan currency must be UAH, USD, or EUR")
    if settings.billing_plan_interval not in {"monthly", "yearly"}:
        raise ValueError("configured billing plan interval must be monthly or yearly")
    if not settings.billing_plan_corpus_set:
        raise ValueError("configured billing plan must entitle at least one corpus")
