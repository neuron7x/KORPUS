"""First login, twice at once, and what an identity provider may not hand itself.

ACT-001 Workstream A. The properties are:

  * an authenticated first login creates an account, once;
  * a repeated login for the same subject returns the same account, including when the two
    logins are concurrent — the case a `SELECT` before an `INSERT` gets wrong;
  * a disabled account cannot use protected functionality;
  * creation is transactional: no account without its audit event, no audit event without
    its account;
  * identity-provider claims do not grant corpus authorization.

The last is the one that would be quiet if it broke. Nothing would fail, nothing would log,
and a provider that started sending a `corpora` claim would be deciding what soldiers may
read.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from korpus.application.accounts import AccountProfile, AccountService, IdentityClaimLeak
from korpus.application.tenancy_ports import AccountDisabled, AccountNotFound
from korpus.domain.tenancy import AccountStatus
from sqlalchemy import func, select

from apps.api.tests.tenancy_fixtures import build_tenancy, reader

#: The barrier only has to make the writers overlap; it is not the thing under test, and a
#: timeout on it measures how loaded the machine is rather than whether the race is handled.
#: Five seconds was enough on an idle laptop and not enough during a mutation run, which is
#: exactly when the suite is most likely to be running. Generous, because the cost of being
#: generous is nothing and the cost of being tight is a red build nobody can reproduce.
BARRIER_SECONDS = 60


def test_a_first_login_creates_exactly_one_account(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        account, created = tenancy.accounts.ensure_account("oidc|alpha", email="a@example.org")
        assert created is True
        again, created_again = tenancy.accounts.ensure_account("oidc|alpha")
        assert created_again is False
        assert again.id == account.id
    finally:
        tenancy.close()


def test_concurrent_first_logins_converge_on_one_account(tmp_path: Path) -> None:
    """Two tabs, one subject. The read-then-write version of this returns two ids.

    Not a theoretical race: a browser restoring a session opens several requests at once,
    and every one of them is a first login until one of them commits.
    """
    tenancy = build_tenancy(tmp_path)
    try:
        results: list[str] = []
        errors: list[BaseException] = []
        start = threading.Barrier(6)

        def login() -> None:
            try:
                start.wait(timeout=BARRIER_SECONDS)
                account, _ = tenancy.accounts.ensure_account("oidc|race")
                results.append(str(account.id))
            except BaseException as error:  # noqa: BLE001 - reported, not swallowed
                errors.append(error)

        threads = [threading.Thread(target=login) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=BARRIER_SECONDS)

        assert not errors, errors
        assert len(results) == 6
        assert len(set(results)) == 1, f"first login produced {len(set(results))} accounts"

        with tenancy.repository.engine.connect() as connection:
            from korpus.infrastructure.tenancy_schema import accounts

            rows = connection.execute(
                select(func.count()).select_from(accounts).where(
                    accounts.c.auth_subject == "oidc|race"
                )
            ).scalar_one()
        assert rows == 1
    finally:
        tenancy.close()


def test_account_creation_writes_its_audit_event_in_the_same_commit(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        from korpus.infrastructure.repository import audits

        before = tenancy.repository.verify_audit().event_count
        account, _ = tenancy.accounts.ensure_account("oidc|audited")
        after = tenancy.repository.verify_audit()
        assert after.event_count == before + 1
        assert after.valid, "the account write broke the audit chain"

        with tenancy.repository.engine.connect() as connection:
            row = connection.execute(
                select(audits.c.action, audits.c.resource_id, audits.c.actor_subject)
                .where(audits.c.action == "account.created")
                .order_by(audits.c.sequence.desc())
            ).first()
        assert row is not None, "an account was created with no audit event"
        assert row[1] == str(account.id)
        assert row[2] == "oidc|audited"
    finally:
        tenancy.close()


def test_a_disabled_account_cannot_use_protected_functionality(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        service: AccountService = tenancy.account_service
        identity = reader("oidc|disabled-later")
        account = service.require_active_account(identity)

        service.disable(reader("operator"), account.id, reason="left the unit")

        with pytest.raises(AccountDisabled):
            service.require_active_account(identity)

        stored = service.get(account.id)
        assert stored.status is AccountStatus.DISABLED
        assert stored.disabled_at is not None, "disabled without a timestamp answers no question"
    finally:
        tenancy.close()


def test_re_enabling_clears_the_disabled_timestamp(tmp_path: Path) -> None:
    """A timestamp left behind says the account is still disabled to anyone reading it."""
    tenancy = build_tenancy(tmp_path)
    try:
        service = tenancy.account_service
        identity = reader("oidc|returns")
        account = service.require_active_account(identity)
        service.disable(reader("operator"), account.id, reason="rotation")
        restored = service.enable(reader("operator"), account.id, reason="returned")

        assert restored.status is AccountStatus.ACTIVE
        assert restored.disabled_at is None
        assert service.require_active_account(identity).id == account.id
    finally:
        tenancy.close()


def test_disabling_requires_a_reason(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        account = tenancy.account_service.require_active_account(reader("oidc|reasoned"))
        with pytest.raises(ValueError):
            tenancy.account_service.disable(reader("operator"), account.id, reason="   ")
    finally:
        tenancy.close()


def test_an_unknown_account_is_a_refusal_not_none(tmp_path: Path) -> None:
    from uuid import uuid4

    tenancy = build_tenancy(tmp_path)
    try:
        with pytest.raises(AccountNotFound):
            tenancy.account_service.get(uuid4())
    finally:
        tenancy.close()


def test_identity_claims_carrying_authorization_are_refused_not_filtered() -> None:
    """The negative control for the boundary this whole module exists to hold.

    Filtering silently would leave a provider configured to send `corpora` believing it had
    taken effect. Refusing means somebody finds out the day they configure it.
    """
    with pytest.raises(IdentityClaimLeak) as refusal:
        AccountProfile.from_claims({"sub": "oidc|x", "corpora": ["restricted"]})
    assert "corpora" in str(refusal.value)

    for field in ("roles", "clearance", "compartments", "entitlements", "permissions", "scope"):
        with pytest.raises(IdentityClaimLeak):
            AccountProfile.from_claims({"sub": "oidc|x", field: ["anything"]})


def test_the_profile_keeps_only_what_a_person_recognises_themselves_by() -> None:
    profile = AccountProfile.from_claims(
        {"sub": "oidc|y", "email": "b@example.org", "name": "Б. Петренко"}
    )
    assert profile.auth_subject == "oidc|y"
    assert profile.email == "b@example.org"
    assert profile.display_name == "Б. Петренко"
    # And nothing else exists on it to carry a decision.
    assert set(vars(profile)) == {"auth_subject", "email", "display_name"}


def test_claims_without_a_subject_are_refused() -> None:
    with pytest.raises(IdentityClaimLeak):
        AccountProfile.from_claims({"email": "c@example.org"})
    with pytest.raises(IdentityClaimLeak):
        AccountProfile.from_claims({"sub": "   "})


def test_an_account_record_carries_no_authorization_field(tmp_path: Path) -> None:
    """The structural half of the rule: there is no field through which money or a
    provider could grant clearance, so no code path can be written that does."""
    tenancy = build_tenancy(tmp_path)
    try:
        account, _ = tenancy.accounts.ensure_account("oidc|structural")
        fields = set(type(account).model_fields)
        assert not fields & {"roles", "clearance", "corpora", "compartments", "permissions"}
    finally:
        tenancy.close()
