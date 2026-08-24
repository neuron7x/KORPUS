"""First login creates an account. Nothing about that grants the right to read anything.

The separation this module holds is the one an authenticated system loses first. A token
arrives, it is valid, the subject is known — and the tempting next line is to treat the
claims in it as the answer to "what may this person read". `AccountService` deliberately
cannot: it returns an `AccountRecord`, which carries a status and no corpora, no clearance
and no compartments. What may be read stays with the entitlement profile and the policy
engine, which never read this table.

`require_active_account` is the whole enforcement surface. It runs before any expensive
work, refuses a disabled account, and returns the account every downstream caller then
uses — so a caller that forgot to check does not get an account to forget it with.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from korpus.application.tenancy_ports import AccountDisabled, AccountNotFound, AccountStore
from korpus.domain.models import Identity
from korpus.domain.tenancy import AccountRecord, AccountStatus

#: Claims that will not be copied into an account, ever. Every one of them is a way an
#: identity provider could hand itself corpus authorization by adding a field to a token:
#: the provider decides who somebody is, this system decides what they may read, and the
#: only thing that crosses the line is a subject.
FORBIDDEN_CLAIM_KEYS = frozenset(
    {"roles", "clearance", "corpora", "compartments", "entitlements", "scope", "permissions"}
)

#: Claims that may be copied, and what they are for. `email` and `name` exist so a person
#: recognises their own account in a list; neither is used to find one — `auth_subject` is.
PROFILE_CLAIM_KEYS = frozenset({"email", "name", "preferred_username"})


class IdentityClaimLeak(RuntimeError):
    """A claim that decides authorization was about to be written into an account.

    Raised rather than filtered. Silently dropping it would leave a provider configured to
    send `corpora` believing it had taken effect, and the day somebody checks is the day
    they discover the profile has been ignored for a year.
    """


@dataclass(frozen=True)
class AccountProfile:
    """The non-authorizing part of a set of claims."""

    auth_subject: str
    email: str | None = None
    display_name: str | None = None

    @classmethod
    def from_claims(cls, claims: dict[str, object]) -> AccountProfile:
        leaked = sorted(FORBIDDEN_CLAIM_KEYS.intersection(claims))
        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise IdentityClaimLeak("claims carry no subject")
        if leaked:
            # The claims may well *contain* these — an OIDC provider commonly sends roles.
            # What is refused is carrying them into the account record, where something
            # downstream could mistake them for a decision this system made.
            raise IdentityClaimLeak(
                f"identity claims carry authorization fields: {', '.join(leaked)}"
            )
        email = claims.get("email")
        name = claims.get("name") or claims.get("preferred_username")
        return cls(
            auth_subject=subject,
            email=str(email)[:320] if isinstance(email, str) and email else None,
            display_name=str(name)[:200] if isinstance(name, str) and name else None,
        )


class AccountService:
    def __init__(self, store: AccountStore) -> None:
        self._store = store

    def login(self, profile: AccountProfile) -> tuple[AccountRecord, bool]:
        """The account for an authenticated subject, created once if it is new.

        Returns `(account, created)`. A disabled account is returned, not raised on: this
        is the record of who logged in, and refusing here would leave the caller unable to
        tell "disabled" from "never existed". `require_active_account` is where the
        refusal belongs, because that is where the protected work starts.
        """
        return self._store.ensure_account(
            profile.auth_subject, email=profile.email, display_name=profile.display_name
        )

    def for_identity(self, identity: Identity) -> AccountRecord:
        """The account behind an authenticated identity, created on first sight.

        Every protected route reaches this, so first login is wherever the person first
        does something rather than a separate registration step that can be skipped.
        """
        account, _created = self._store.ensure_account(identity.subject)
        return account

    def require_active_account(self, identity: Identity) -> AccountRecord:
        account = self.for_identity(identity)
        if account.status is not AccountStatus.ACTIVE:
            raise AccountDisabled(str(account.id))
        return account

    def disable(self, actor: Identity, account_id: UUID, reason: str) -> AccountRecord:
        if not reason.strip():
            raise ValueError("disabling an account requires a reason")
        return self._store.set_account_status(
            actor.subject, account_id, AccountStatus.DISABLED, reason=reason.strip()
        )

    def enable(self, actor: Identity, account_id: UUID, reason: str) -> AccountRecord:
        if not reason.strip():
            raise ValueError("re-enabling an account requires a reason")
        return self._store.set_account_status(
            actor.subject, account_id, AccountStatus.ACTIVE, reason=reason.strip()
        )

    def get(self, account_id: UUID) -> AccountRecord:
        account = self._store.get_account(account_id)
        if account is None:
            raise AccountNotFound(str(account_id))
        return account
