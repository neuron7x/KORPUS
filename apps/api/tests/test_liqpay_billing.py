"""Adversarial proof for the production payment seam.

Checkout is server-authored; callbacks are provider-authenticated; neither the browser nor
an otherwise valid callback may change price, currency, account ownership or lifecycle.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from korpus.application.checkout import CheckoutService
from korpus.application.subscriptions import SubscriptionService
from korpus.application.tenancy_ports import BillingEventIgnored, BillingEventRejected
from korpus.domain.tenancy import (
    BillingEventResult,
    BillingInterval,
    PlanRecord,
    SubscriptionStatus,
)
from korpus.infrastructure.liqpay import CHECKOUT_URL, LiqPayBillingProvider
from pydantic import ValidationError

from apps.api.tests.tenancy_fixtures import build_tenancy

PUBLIC = "sandbox_public"
PRIVATE = "sandbox_private"
BASE = "https://korpus.example"


def _provider() -> LiqPayBillingProvider:
    return LiqPayBillingProvider(PUBLIC, PRIVATE)


def _event(provider: LiqPayBillingProvider, **changes: object) -> tuple[bytes, str]:
    event: dict[str, object] = {
        "public_key": PUBLIC,
        "action": "subscribe",
        "status": "subscribed",
        "transaction_id": 991337,
        "order_id": "00000000-0000-0000-0000-000000000001",
        "amount": "199.00",
        "currency": "UAH",
        "end_date": int((datetime.now(UTC) - timedelta(minutes=1)).timestamp() * 1000),
    }
    event.update(changes)
    data = base64.b64encode(
        json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return data.encode("ascii"), provider.sign_data(data)


def _sellable(tenancy, *, interval: BillingInterval = BillingInterval.MONTHLY) -> PlanRecord:
    return tenancy.subscriptions.upsert_plan(
        PlanRecord(
            code="standard",
            name="Standard",
            billing_interval=interval,
            price_minor=19_900,
            currency="UAH",
            entitled_corpora=frozenset({"training"}),
        )
    )


def test_plan_price_and_currency_are_one_domain_value() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        PlanRecord(code="broken", name="Broken", price_minor=100)
    with pytest.raises(ValidationError, match="configured together"):
        PlanRecord(code="broken", name="Broken", currency="UAH")


def test_checkout_uses_only_server_plan_values(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        account, _ = tenancy.accounts.ensure_account("oidc|payer")
        plan = _sellable(tenancy)
        provider = _provider()
        subscriptions = SubscriptionService(tenancy.subscriptions, tenancy.accounts, provider)
        checkout = CheckoutService(
            tenancy.accounts, tenancy.subscriptions, subscriptions, provider, BASE
        )

        descriptor = checkout.start("oidc|payer", account.id, plan.code)
        assert descriptor.provider == "liqpay"
        assert descriptor.action_url == CHECKOUT_URL
        assert descriptor.method == "POST"
        data = descriptor.fields["data"]
        assert descriptor.fields["signature"] == provider.sign_data(data)
        decoded = json.loads(base64.b64decode(data).decode("utf-8"))
        assert decoded["amount"] == "199.00"
        assert decoded["currency"] == "UAH"
        assert decoded["action"] == "subscribe"
        assert decoded["subscribe"] == "1"
        assert decoded["subscribe_periodicity"] == "month"
        assert decoded["order_id"] == str(descriptor.subscription_id)
        assert decoded["customer"] == str(account.id)
        assert decoded["server_url"] == f"{BASE}/v1/billing/liqpay/callback"
        assert decoded["result_url"] == f"{BASE}/?billing=return"

        stored = tenancy.subscriptions.get_subscription(descriptor.subscription_id)
        assert stored is not None
        assert stored.status is SubscriptionStatus.INCOMPLETE
    finally:
        tenancy.close()


def test_wrong_signature_and_other_merchant_are_rejected(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        provider = _provider()
        service = SubscriptionService(tenancy.subscriptions, tenancy.accounts, provider)
        payload, signature = _event(provider)
        with pytest.raises(BillingEventRejected):
            service.handle_event(payload, "bad")

        payload, signature = _event(provider, public_key="another_merchant")
        with pytest.raises(BillingEventRejected):
            service.handle_event(payload, signature)
    finally:
        tenancy.close()


def test_non_final_callback_is_acknowledge_only(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        provider = _provider()
        service = SubscriptionService(tenancy.subscriptions, tenancy.accounts, provider)
        payload, signature = _event(provider, status="processing")
        with pytest.raises(BillingEventIgnored):
            service.handle_event(payload, signature)
    finally:
        tenancy.close()


def test_signed_amount_tampering_cannot_activate_access(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        account, _ = tenancy.accounts.ensure_account("oidc|payer")
        plan = _sellable(tenancy)
        provider = _provider()
        service = SubscriptionService(tenancy.subscriptions, tenancy.accounts, provider)
        subscription = service.start_subscription("oidc|payer", account.id, plan.code)
        payload, signature = _event(
            provider,
            order_id=str(subscription.id),
            transaction_id=77,
            amount="1.00",
        )

        assert service.handle_event(payload, signature) is BillingEventResult.REJECTED
        stored = tenancy.subscriptions.get_subscription(subscription.id)
        assert stored is not None
        assert stored.status is SubscriptionStatus.INCOMPLETE
    finally:
        tenancy.close()


def test_final_callback_activates_once_and_bounds_the_period(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        account, _ = tenancy.accounts.ensure_account("oidc|payer")
        plan = _sellable(tenancy)
        provider = _provider()
        service = SubscriptionService(tenancy.subscriptions, tenancy.accounts, provider)
        subscription = service.start_subscription("oidc|payer", account.id, plan.code)
        occurred = datetime.now(UTC) - timedelta(minutes=1)
        occurred = occurred.replace(microsecond=(occurred.microsecond // 1000) * 1000)
        payload, signature = _event(
            provider,
            order_id=str(subscription.id),
            transaction_id=78,
            end_date=int(occurred.timestamp() * 1000),
        )

        assert service.handle_event(payload, signature) is BillingEventResult.APPLIED
        assert service.handle_event(payload, signature) is BillingEventResult.DUPLICATE
        stored = tenancy.subscriptions.get_subscription(subscription.id)
        assert stored is not None
        assert stored.status is SubscriptionStatus.ACTIVE
        assert stored.current_period_start == occurred
        assert stored.current_period_end is not None
        assert stored.current_period_end > occurred
        expected_month = 1 if occurred.month == 12 else occurred.month + 1
        expected_year = occurred.year + (1 if occurred.month == 12 else 0)
        assert stored.current_period_end.year == expected_year
        assert stored.current_period_end.month == expected_month
    finally:
        tenancy.close()


def test_yearly_checkout_declares_yearly_recurrence(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        account, _ = tenancy.accounts.ensure_account("oidc|year")
        plan = _sellable(tenancy, interval=BillingInterval.YEARLY)
        provider = _provider()
        service = SubscriptionService(tenancy.subscriptions, tenancy.accounts, provider)
        checkout = CheckoutService(tenancy.accounts, tenancy.subscriptions, service, provider, BASE)
        descriptor = checkout.start("oidc|year", account.id, plan.code)
        body = json.loads(base64.b64decode(descriptor.fields["data"]).decode("utf-8"))
        assert body["subscribe_periodicity"] == "year"
    finally:
        tenancy.close()


def test_http_checkout_and_callback_are_one_fail_closed_flow(tmp_path: Path) -> None:
    from urllib.parse import urlencode

    from fastapi.testclient import TestClient
    from korpus.config import Settings
    from korpus.domain.models import AccessTier, Identity
    from korpus.main import create_app
    from korpus.security.auth import get_identity

    from apps.api.tests.conftest import IdentityProvider

    settings = Settings(
        environment="test",
        schema_mode="auto",
        database_url=f"sqlite:///{tmp_path / 'liqpay-api.db'}",
        object_root=tmp_path / "objects-api",
        audit_anchor_path=tmp_path / "anchor-api.json",
        audit_hmac_key="liqpay-api-audit",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        min_retrieval_score=0.08,
        min_query_coverage=0.15,
        min_support_score=0.08,
        liqpay_public_key=PUBLIC,
        liqpay_private_key=PRIVATE,
        billing_public_base_url=BASE,
    )
    app = create_app(settings)
    identity = Identity(
        subject="oidc|http-payer",
        roles=frozenset({"user"}),
        clearance=AccessTier.AUTHENTICATED,
        corpora=frozenset({"training"}),
    )
    app.dependency_overrides[get_identity] = IdentityProvider(identity)

    with TestClient(app) as client:
        account = client.get("/v1/account")
        assert account.status_code == 200, account.text
        plan = client.app.state.subscription_store.upsert_plan(
            PlanRecord(
                code="standard",
                name="Standard",
                price_minor=19_900,
                currency="UAH",
                entitled_corpora=frozenset({"training"}),
            )
        )

        plans = client.get("/v1/plans")
        assert plans.status_code == 200
        view = next(item for item in plans.json() if item["code"] == plan.code)
        assert view["price_minor"] == 19_900
        assert view["currency"] == "UAH"
        assert view["sellable"] is True

        started = client.post("/v1/billing/checkout", json={"plan_code": plan.code})
        assert started.status_code == 201, started.text
        descriptor = started.json()
        assert descriptor["action_url"] == CHECKOUT_URL
        checkout_body = json.loads(base64.b64decode(descriptor["fields"]["data"]))
        assert checkout_body["order_id"] == descriptor["subscription_id"]
        assert client.get("/v1/subscription").json()["subscription_status"] == "incomplete"

        provider: LiqPayBillingProvider = client.app.state.billing_provider
        event, signature = _event(
            provider,
            order_id=descriptor["subscription_id"],
            transaction_id=8801,
        )
        callback = client.post(
            "/v1/billing/liqpay/callback",
            content=urlencode({"data": event.decode("ascii"), "signature": signature}),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert callback.status_code == 200, callback.text
        assert callback.text == "applied"
        entitlement = client.get("/v1/subscription").json()
        assert entitlement["subscription_status"] == "active"
        assert entitlement["entitled_corpora"] == ["training"]

        duplicate = client.post(
            "/v1/billing/liqpay/callback",
            content=urlencode({"data": event.decode("ascii"), "signature": signature}),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert duplicate.status_code == 200
        assert duplicate.text == "duplicate"


def test_http_callback_rejects_signed_wrong_amount(tmp_path: Path) -> None:
    from urllib.parse import urlencode

    from fastapi.testclient import TestClient
    from korpus.config import Settings
    from korpus.domain.models import AccessTier, Identity
    from korpus.main import create_app
    from korpus.security.auth import get_identity

    from apps.api.tests.conftest import IdentityProvider

    settings = Settings(
        environment="test",
        schema_mode="auto",
        database_url=f"sqlite:///{tmp_path / 'liqpay-tamper-api.db'}",
        object_root=tmp_path / "objects-tamper",
        audit_anchor_path=tmp_path / "anchor-tamper.json",
        audit_hmac_key="liqpay-api-audit",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        min_retrieval_score=0.08,
        min_query_coverage=0.15,
        min_support_score=0.08,
        liqpay_public_key=PUBLIC,
        liqpay_private_key=PRIVATE,
        billing_public_base_url=BASE,
    )
    app = create_app(settings)
    identity = Identity(
        subject="oidc|tamper-payer",
        roles=frozenset({"user"}),
        clearance=AccessTier.AUTHENTICATED,
        corpora=frozenset({"training"}),
    )
    app.dependency_overrides[get_identity] = IdentityProvider(identity)

    with TestClient(app) as client:
        client.get("/v1/account")
        client.app.state.subscription_store.upsert_plan(
            PlanRecord(
                code="standard",
                name="Standard",
                price_minor=19_900,
                currency="UAH",
                entitled_corpora=frozenset({"training"}),
            )
        )
        descriptor = client.post("/v1/billing/checkout", json={"plan_code": "standard"}).json()
        provider: LiqPayBillingProvider = client.app.state.billing_provider
        event, signature = _event(
            provider,
            order_id=descriptor["subscription_id"],
            transaction_id=8802,
            amount="1.00",
        )
        callback = client.post(
            "/v1/billing/liqpay/callback",
            content=urlencode({"data": event.decode("ascii"), "signature": signature}),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert callback.status_code == 200
        assert callback.text == "rejected"
        # The provider was authentic, but the commercial claim was not. Access remains shut.
        entitlement = client.get("/v1/subscription").json()
        assert entitlement["subscription_status"] == "incomplete"
        assert entitlement["entitled_corpora"] == []


def test_deployment_plan_bootstrap_is_idempotent(tmp_path: Path) -> None:
    from korpus.config import Settings
    from korpus.main import create_app

    database = tmp_path / "bootstrap.db"
    settings = Settings(
        environment="test",
        auth_mode="disabled",
        database_url=f"sqlite:///{database}",
        billing_plan_code="standard",
        billing_plan_name="Standard",
        billing_plan_price_minor=19_900,
        billing_plan_currency="UAH",
        billing_plan_interval="monthly",
        billing_plan_corpora="training,doctrine",
    )
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as first:
        plan = first.app.state.subscription_store.get_plan_by_code("standard")
        assert plan is not None
        assert plan.price_minor == 19_900
        assert plan.currency == "UAH"
        assert plan.entitled_corpora == frozenset({"training", "doctrine"})

    with TestClient(create_app(settings)) as second:
        plans = second.app.state.subscription_store.list_plans()
        assert [item.code for item in plans] == ["standard"]
        assert plans[0].id == plan.id


def test_configured_plan_refuses_incomplete_commercial_terms() -> None:
    from korpus.config import Settings

    with pytest.raises(ValueError, match="billing_plan_price_minor"):
        Settings(
            environment="test",
            auth_mode="disabled",
            billing_plan_code="standard",
            billing_plan_corpora="training",
        )
    with pytest.raises(ValueError, match="at least one corpus"):
        Settings(
            environment="test",
            auth_mode="disabled",
            billing_plan_code="standard",
            billing_plan_price_minor=19_900,
        )
