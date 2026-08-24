"""Switching an account off, by somebody who is not holding a database shell.

`AccountService.disable` was written with ACT-001 — transactional, audited, and covered by
a threat test proving a disabled account is refused everywhere. It was reachable from a
Python REPL with the database credentials and from nowhere else.

That is the gap these tests close, and the shape is worth naming: a capability that exists,
is correct, is tested, and cannot be invoked. Nothing about it looks wrong in review. It
fails only when somebody at three in the morning needs to stop a compromised login and the
answer is "wake an engineer".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.main import create_app
from korpus.security.auth import get_identity

from apps.api.tests.conftest import IdentityProvider

ADMIN = Identity(
    subject="oidc|duty-admin",
    roles=frozenset({"admin"}),
    clearance=AccessTier.RESTRICTED,
    corpora=frozenset({"public"}),
)
REVIEWER = Identity(
    subject="oidc|reviewer",
    roles=frozenset({"reviewer"}),
    clearance=AccessTier.RESTRICTED,
    corpora=frozenset({"public"}),
)
SOLDIER = Identity(
    subject="oidc|soldier",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public"}),
)


@pytest.fixture
def client(tmp_path: Path) -> Any:
    settings = Settings(
        environment="test",
        schema_mode="auto",
        database_url=f"sqlite:///{tmp_path / 'admin.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="admin-test-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
    )
    app = create_app(settings)
    provider = IdentityProvider(ADMIN)
    app.dependency_overrides[get_identity] = provider
    with TestClient(app) as test_client:
        test_client.identity_provider = provider  # type: ignore[attr-defined]
        yield test_client


def _as(client: Any, identity: Identity) -> None:
    client.identity_provider.current = identity


def _account_of(client: Any, identity: Identity) -> str:
    """First contact creates the account, exactly as a login would."""
    _as(client, identity)
    return client.get("/v1/account").json()["id"]


def test_an_operator_can_disable_an_account_without_a_database_shell(client: Any) -> None:
    soldier = _account_of(client, SOLDIER)
    _as(client, ADMIN)

    response = client.post(
        f"/v1/admin/accounts/{soldier}/status",
        json={"status": "disabled", "reason": "посвідчення скомпрометовано"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "disabled"

    # And the block is the one the threat test already proved holds.
    _as(client, SOLDIER)
    refused = client.get("/v1/conversations")
    assert refused.status_code == 403
    assert refused.json()["detail"]["reason"] == "account_disabled"


def test_the_same_operator_can_put_it_back(client: Any) -> None:
    soldier = _account_of(client, SOLDIER)
    _as(client, ADMIN)
    client.post(
        f"/v1/admin/accounts/{soldier}/status",
        json={"status": "disabled", "reason": "перевірка інциденту"},
    )
    restored = client.post(
        f"/v1/admin/accounts/{soldier}/status",
        json={"status": "active", "reason": "інцидент закрито, доступ повернуто"},
    )

    assert restored.status_code == 200
    assert restored.json()["status"] == "active"
    _as(client, SOLDIER)
    assert client.get("/v1/conversations").status_code == 200


def test_only_an_administrator_may_switch_a_person_off(client: Any) -> None:
    """A reviewer can approve a document. That is not the same authority."""
    soldier = _account_of(client, SOLDIER)

    for identity in (REVIEWER, SOLDIER):
        _as(client, identity)
        response = client.post(
            f"/v1/admin/accounts/{soldier}/status",
            json={"status": "disabled", "reason": "спроба без повноважень"},
        )
        assert response.status_code == 403, f"{sorted(identity.roles)} disabled an account"
        assert response.json()["detail"]["reason"] == "account_management_not_permitted"

    _as(client, SOLDIER)
    assert client.get("/v1/conversations").status_code == 200, "the account was switched off"


def test_listing_and_lookup_are_administrator_only(client: Any) -> None:
    """Enumerating who exists is itself a capability, not a convenience."""
    _account_of(client, SOLDIER)
    _as(client, REVIEWER)
    assert client.get("/v1/admin/accounts").status_code == 403
    assert client.get(f"/v1/admin/accounts/{SOLDIER.subject}").status_code == 403


def test_an_administrator_cannot_disable_the_account_they_are_using(client: Any) -> None:
    """It would lock out the role that has to undo it, and most deployments have one."""
    admin_account = _account_of(client, ADMIN)

    response = client.post(
        f"/v1/admin/accounts/{admin_account}/status",
        json={"status": "disabled", "reason": "помилковий вибір рядка у списку"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason"] == "cannot_disable_your_own_account"
    assert client.get("/v1/account").json()["status"] == "active"


def test_an_administrator_may_still_re_enable_themselves(client: Any) -> None:
    """The guard is about lockout, not about self-service. Enabling cannot cause one."""
    admin_account = _account_of(client, ADMIN)
    response = client.post(
        f"/v1/admin/accounts/{admin_account}/status",
        json={"status": "active", "reason": "підтвердження чинності після інциденту"},
    )
    assert response.status_code == 200


def test_a_reason_short_enough_to_be_meaningless_is_refused(client: Any) -> None:
    soldier = _account_of(client, SOLDIER)
    _as(client, ADMIN)

    for reason in ("", "x", "test", "asdf"):
        response = client.post(
            f"/v1/admin/accounts/{soldier}/status",
            json={"status": "disabled", "reason": reason},
        )
        assert response.status_code == 422, f"{reason!r} was accepted as a reason"

    _as(client, SOLDIER)
    assert client.get("/v1/conversations").status_code == 200


def test_an_unknown_status_is_refused_by_the_contract(client: Any) -> None:
    soldier = _account_of(client, SOLDIER)
    _as(client, ADMIN)
    response = client.post(
        f"/v1/admin/accounts/{soldier}/status",
        json={"status": "deleted", "reason": "стан, якого не існує"},
    )
    assert response.status_code == 422


def test_an_unknown_account_is_a_404_not_a_500(client: Any) -> None:
    _as(client, ADMIN)
    assert (
        client.post(
            f"/v1/admin/accounts/{uuid4()}/status",
            json={"status": "disabled", "reason": "акаунт, якого немає"},
        ).status_code
        == 404
    )
    assert client.get("/v1/admin/accounts/oidc%7Cnobody").status_code == 404


def test_the_change_reaches_the_audit_chain_with_its_reason(client: Any) -> None:
    from korpus.infrastructure.repository import audits
    from sqlalchemy import select

    soldier = _account_of(client, SOLDIER)
    _as(client, ADMIN)
    client.post(
        f"/v1/admin/accounts/{soldier}/status",
        json={"status": "disabled", "reason": "втрата пристрою, підтверджено командиром"},
    )

    with client.app.state.repository.engine.connect() as connection:
        row = connection.execute(
            select(audits.c.actor_subject, audits.c.payload_json)
            .where(audits.c.action == "account.disabled")
            .order_by(audits.c.sequence.desc())
        ).first()

    assert row is not None, "an account was disabled with no audit event"
    assert row[0] == ADMIN.subject, "the change was not attributed to the operator"
    assert "втрата пристрою" in row[1]
    assert client.app.state.repository.verify_audit().valid


def test_an_operator_can_find_the_account_by_the_subject_they_were_given(
    client: Any,
) -> None:
    """An incident arrives as a login, not as a UUID."""
    expected = _account_of(client, SOLDIER)
    _as(client, ADMIN)

    found = client.get(f"/v1/admin/accounts/{SOLDIER.subject}")

    assert found.status_code == 200, found.text
    assert found.json()["id"] == expected


def test_the_listing_can_answer_whether_it_is_actually_off(client: Any) -> None:
    soldier = _account_of(client, SOLDIER)
    _account_of(client, REVIEWER)
    _as(client, ADMIN)
    client.post(
        f"/v1/admin/accounts/{soldier}/status",
        json={"status": "disabled", "reason": "перевірка після інциденту"},
    )

    everyone = client.get("/v1/admin/accounts").json()
    disabled = client.get("/v1/admin/accounts?disabled_only=true").json()

    assert len(everyone) == 3, "the operator's own account is missing from the listing"
    assert [item["id"] for item in disabled] == [soldier]


def test_a_disabled_administrator_cannot_administer(client: Any) -> None:
    """The attack this guards: an account is switched off because it is compromised.

    Checking only the role let a disabled administrator keep administering — including
    re-enabling themselves, which makes disabling a suggestion. Found by writing the
    listing test and noticing the operator had no account row at all.
    """
    first = _account_of(client, ADMIN)
    second_admin = Identity(
        subject="oidc|second-admin",
        roles=frozenset({"admin"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )
    _account_of(client, second_admin)

    # Another administrator switches the first one off — the path that exists precisely
    # because you cannot disable yourself.
    _as(client, second_admin)
    disabled = client.post(
        f"/v1/admin/accounts/{first}/status",
        json={"status": "disabled", "reason": "обліковий запис скомпрометовано"},
    )
    assert disabled.status_code == 200, disabled.text

    _as(client, ADMIN)
    for method, path, body in (
        ("get", "/v1/admin/accounts", None),
        ("get", f"/v1/admin/accounts/{second_admin.subject}", None),
        (
            "post",
            f"/v1/admin/accounts/{first}/status",
            {"status": "active", "reason": "спроба самостійно повернути доступ"},
        ),
    ):
        response = client.get(path) if method == "get" else client.post(path, json=body)
        assert response.status_code == 403, f"a disabled administrator reached {path}"
        assert response.json()["detail"]["reason"] == "account_disabled"

    # And it is still off: the attempt to re-enable did not take.
    _as(client, second_admin)
    assert client.get(f"/v1/admin/accounts/{ADMIN.subject}").json()["status"] == "disabled"


def test_being_switched_off_and_not_being_an_admin_are_different_answers(
    client: Any,
) -> None:
    """One 403 for both would send somebody to argue about permissions for an hour."""
    _account_of(client, REVIEWER)
    _as(client, REVIEWER)
    not_admin = client.get("/v1/admin/accounts")
    assert not_admin.json()["detail"]["reason"] == "account_management_not_permitted"

    admin_account = _account_of(client, ADMIN)
    second = Identity(
        subject="oidc|third-admin",
        roles=frozenset({"admin"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )
    _account_of(client, second)
    _as(client, second)
    client.post(
        f"/v1/admin/accounts/{admin_account}/status",
        json={"status": "disabled", "reason": "перевірка розрізнення відмов"},
    )
    _as(client, ADMIN)
    switched_off = client.get("/v1/admin/accounts")
    assert switched_off.json()["detail"]["reason"] == "account_disabled"
    assert switched_off.json()["detail"]["reason"] != not_admin.json()["detail"]["reason"]
