"""The ACT-001 endpoints as a client meets them.

Everything below goes through the running application: real routing, real dependencies,
real database. The unit tests above prove the rules; these prove the rules are reachable
and that the wiring did not quietly skip one.

The ordering test is the one worth reading twice. A paywall enforced *after* retrieval
costs an unpaid request exactly as much as a paid one, which turns a subscription check
into a denial-of-service amplifier. It is asserted by counting how far the request got,
not by reading the code.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from korpus.application.paid_access import EntitlementProjection
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.domain.tenancy import PlanRecord
from korpus.main import create_app
from korpus.security.auth import get_identity

from apps.api.tests.conftest import IdentityProvider
from apps.api.tests.helpers import approve, ingest_text

SECRET = "b" * 48


def _identity(subject: str, corpora: frozenset[str] = frozenset({"public"})) -> Identity:
    return Identity(
        subject=subject,
        roles=frozenset({"user", "curator", "reviewer", "admin"}),
        clearance=AccessTier.RESTRICTED,
        corpora=corpora,
    )


@pytest.fixture
def tenant_client(tmp_path: Path) -> Any:
    settings = Settings(
        environment="test",
        schema_mode="auto",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="tenancy-api-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        min_retrieval_score=0.08,
        min_query_coverage=0.15,
        min_support_score=0.08,
        billing_webhook_secret=SECRET,
    )
    app = create_app(settings)
    provider = IdentityProvider(_identity("oidc|api-user"))
    app.dependency_overrides[get_identity] = provider
    with TestClient(app) as client:
        client.identity_provider = provider  # type: ignore[attr-defined]
        yield client


def test_the_account_endpoint_creates_on_first_call_and_is_stable(tenant_client: Any) -> None:
    first = tenant_client.get("/v1/account")
    second = tenant_client.get("/v1/account")

    assert first.status_code == 200, first.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "active"
    # No authorization field crosses the boundary.
    assert not {"roles", "clearance", "corpora", "compartments"} & set(first.json())


def test_a_disabled_account_is_refused_everywhere(tenant_client: Any) -> None:
    account_id = tenant_client.get("/v1/account").json()["id"]
    service = tenant_client.app.state.account_service
    from uuid import UUID

    service.disable(_identity("operator"), UUID(account_id), reason="test")

    for method, path in (
        ("get", "/v1/account"),
        ("get", "/v1/plans"),
        ("get", "/v1/conversations"),
        ("get", "/v1/subscription"),
    ):
        response = getattr(tenant_client, method)(path)
        assert response.status_code == 403, f"{path} served a disabled account"
        assert response.json()["detail"]["reason"] == "account_disabled"

    created = tenant_client.post("/v1/conversations", json={"title": "x"})
    assert created.status_code == 403


def test_conversations_are_created_listed_and_archived(tenant_client: Any) -> None:
    created = tenant_client.post("/v1/conversations", json={"title": "турнікет"})
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]

    listed = tenant_client.get("/v1/conversations")
    assert [item["id"] for item in listed.json()] == [conversation_id]

    archived = tenant_client.post(f"/v1/conversations/{conversation_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert tenant_client.get("/v1/conversations").json() == []
    assert (
        len(tenant_client.get("/v1/conversations?include_archived=true").json()) == 1
    )
    assert tenant_client.post(f"/v1/conversations/{conversation_id}/archive").status_code == 409


def test_another_account_gets_404_for_a_conversation_it_does_not_own(
    tenant_client: Any,
) -> None:
    conversation_id = tenant_client.post("/v1/conversations", json={}).json()["id"]

    tenant_client.identity_provider.current = _identity("oidc|intruder")
    for method, path in (
        ("get", f"/v1/conversations/{conversation_id}"),
        ("post", f"/v1/conversations/{conversation_id}/archive"),
    ):
        response = getattr(tenant_client, method)(path)
        assert response.status_code == 404, f"{path} leaked another account's conversation"

    asked = tenant_client.post(
        f"/v1/conversations/{conversation_id}/ask", json={"text": "чуже питання"}
    )
    assert asked.status_code == 404


def test_a_question_inside_a_conversation_is_answered_and_recorded(
    tenant_client: Any,
) -> None:
    version = ingest_text(
        tenant_client,
        title="Настанова з тактичної медицини",
        text="Турнікет накладається вище рани на п'ять сантиметрів.",
    )
    approve(tenant_client, version["version"]["id"])

    conversation_id = tenant_client.post("/v1/conversations", json={}).json()["id"]
    response = tenant_client.post(
        f"/v1/conversations/{conversation_id}/ask",
        json={"text": "як накладається турнікет"},
    )
    assert response.status_code == 200, response.text
    answer = response.json()

    stored = tenant_client.get(f"/v1/conversations/{conversation_id}").json()
    assert [message["role"] for message in stored] == ["user", "assistant"]
    assert stored[1]["answer_id"] == answer["id"]


def test_an_inactive_subscription_is_refused_before_retrieval_runs(
    tenant_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering property, measured rather than read.

    `execute` is replaced with a function that records being called. A 402 with the
    counter at zero is the whole claim: the refusal happened before the expensive work.
    """
    store = tenant_client.app.state.subscription_store
    store.upsert_plan(
        PlanRecord(code="standard", name="Standard", entitled_corpora=frozenset({"training"}))
    )
    tenant_client.app.state.entitlements = EntitlementProjection(
        store, tenant_client.app.state.policy, subscription_required=True
    )

    conversation_id = tenant_client.post("/v1/conversations", json={}).json()["id"]

    calls: list[str] = []
    from korpus.application.answer_query import ExtractiveAnswerService

    original = ExtractiveAnswerService.execute

    def counted(self: Any, identity: Any, query: Any) -> Any:
        calls.append(query.text)
        return original(self, identity, query)

    monkeypatch.setattr(ExtractiveAnswerService, "execute", counted)

    response = tenant_client.post(
        f"/v1/conversations/{conversation_id}/ask", json={"text": "як накласти турнікет"}
    )

    assert response.status_code == 402, response.text
    assert response.json()["detail"]["reason"] == "no_active_subscription"
    assert calls == [], "retrieval ran before the subscription was checked"
    # And nothing was written into the history for a request that was refused.
    assert tenant_client.get(f"/v1/conversations/{conversation_id}").json() == []


def test_the_entitlement_endpoint_says_whether_it_is_enforced(tenant_client: Any) -> None:
    body = tenant_client.get("/v1/subscription").json()
    assert body["enforced"] is False
    assert body["reason"] == "no_subscription"
    assert body["entitled_corpora"] == []


def test_starting_a_subscription_never_produces_an_active_one(tenant_client: Any) -> None:
    store = tenant_client.app.state.subscription_store
    store.upsert_plan(
        PlanRecord(code="standard", name="Standard", entitled_corpora=frozenset({"public"}))
    )

    assert [plan["code"] for plan in tenant_client.get("/v1/plans").json()] == ["standard"]

    created = tenant_client.post("/v1/subscription", json={"plan_code": "standard"})
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "incomplete"

    missing = tenant_client.post("/v1/subscription", json={"plan_code": "nope"})
    assert missing.status_code == 404


def test_the_webhook_refuses_an_unsigned_body(tenant_client: Any) -> None:
    response = tenant_client.post("/v1/billing/webhook", content=b'{"id":"e","type":"x"}')
    assert response.status_code == 400


def test_the_webhook_applies_a_signed_event_without_any_session(tenant_client: Any) -> None:
    """A payment provider holds no account here. The signature is the whole authentication."""
    import hashlib
    import hmac

    store = tenant_client.app.state.subscription_store
    store.upsert_plan(
        PlanRecord(code="standard", name="Standard", entitled_corpora=frozenset({"public"}))
    )
    subscription_id = tenant_client.post(
        "/v1/subscription", json={"plan_code": "standard"}
    ).json()["id"]

    moment = datetime.now(UTC)
    body = json.dumps(
        {
            "id": "evt-http-1",
            "type": "subscription.activated",
            "occurred_at": moment.isoformat(),
            "data": {
                "reference": subscription_id,
                "period_start": moment.isoformat(),
                "period_end": (moment + timedelta(days=30)).isoformat(),
            },
        }
    ).encode("utf-8")
    signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

    applied = tenant_client.post(
        "/v1/billing/webhook", content=body, headers={"X-Korpus-Signature": signature}
    )
    assert applied.status_code == 200, applied.text
    assert applied.text == "applied"

    duplicate = tenant_client.post(
        "/v1/billing/webhook", content=body, headers={"X-Korpus-Signature": signature}
    )
    assert duplicate.status_code == 200
    assert duplicate.text == "duplicate"

    assert tenant_client.get("/v1/subscription").json()["subscription_status"] == "active"


def test_an_unknown_conversation_id_is_a_404_not_a_500(tenant_client: Any) -> None:
    response = tenant_client.get(f"/v1/conversations/{uuid4()}")
    assert response.status_code == 404


def test_the_openapi_document_describes_the_new_surface(tenant_client: Any) -> None:
    """Contract drift: the routes exist and are described where a client will look."""
    spec = tenant_client.get("/openapi.json").json()
    for path in (
        "/v1/account",
        "/v1/plans",
        "/v1/subscription",
        "/v1/conversations",
        "/v1/conversations/{conversation_id}",
        "/v1/conversations/{conversation_id}/archive",
        "/v1/conversations/{conversation_id}/ask",
    ):
        assert path in spec["paths"], f"{path} is missing from the OpenAPI document"
    # The webhook is excluded on purpose: it is not part of the client contract, and
    # publishing it invites a request from something that has no signature.
    assert "/v1/billing/webhook" not in spec["paths"]


def test_the_transcript_carries_the_verdict_the_reader_was_shown(
    tenant_client: Any,
) -> None:
    """End to end: a refusal read back is still a refusal.

    Reproduces what a browser showed before the verdict was stored — the answer text alone,
    which for a refusal reads as a paragraph indistinguishable from an answer.
    """
    conversation_id = tenant_client.post("/v1/conversations", json={}).json()["id"]
    asked = tenant_client.post(
        f"/v1/conversations/{conversation_id}/ask",
        json={"text": "питання, на яке порожній корпус не має відповіді"},
    )
    assert asked.status_code == 200, asked.text
    status = asked.json()["status"]

    stored = tenant_client.get(f"/v1/conversations/{conversation_id}").json()
    assert stored[0]["answer_status"] is None, "a question is not a verdict"
    assert stored[1]["answer_status"] == status
