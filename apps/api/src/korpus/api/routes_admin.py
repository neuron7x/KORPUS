"""Disabling an account — the control that existed and could not be invoked.

`AccountService.disable` was written with ACT-001: transactional, audited, and covered by a
threat test proving a disabled account is refused everywhere. It was reachable from a
Python REPL with the database credentials and from nowhere else. No route, no console, no
command.

WEB-001's acceptance predicate is that every critical workflow runs without raw database or
API manipulation, and stopping a compromised account is as critical as a workflow gets: it
happens at three in the morning, and the person doing it is on their phone. A control whose
only invocation path is an engineer with a shell is not a control — it is a capability
somebody would have to be woken up to use.

Three rules hold here and each is refused rather than sanitised:

  admin only          `account:manage` is held by no role but `admin`. A reviewer who can
                      approve a document cannot switch a person off.
  a reason, always    it goes into the audit chain as the operator's assertion. "Somebody
                      disabled this in August" is not an answer to why.
  never yourself      an admin disabling their own account locks out the role that would
                      have to undo it. The deployment ships with one admin more often than
                      not.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from korpus.api.routes_tenancy import (
    AccountServiceDependency,
    AccountView,
    IdentityDependency,
    _account_view,
    account_for,
    get_account_store,
)
from korpus.application.accounts import AccountService
from korpus.application.policy import AuthorizationError, PolicyEngine
from korpus.application.tenancy_ports import AccountNotFound, AccountStore
from korpus.domain.models import Identity
from korpus.domain.tenancy import AccountStatus

admin_router = APIRouter()

#: Held by `admin` alone, through the wildcard in `ROLE_PERMISSIONS`. Named rather than
#: checking `has_role("admin")` so the decision stays with the policy engine: a deployment
#: that later gives a `security-officer` role this permission changes one table, not this
#: file.
ACCOUNT_MANAGE = "account:manage"


class AccountStatusChange(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")
    #: Long enough to be a sentence. "test", "x" and "asdf" are what a required field
    #: collects when the requirement is only that it is non-empty.
    reason: str = Field(min_length=8, max_length=500)


def _require_admin(identity: Identity, service: AccountService) -> None:
    """Active account first, then the permission. Both, and in that order.

    The first version checked only the role, which meant a disabled administrator could
    still administer — and therefore re-enable themselves. That is the attack: an account
    is switched off precisely because it is compromised, and leaving it able to undo that
    makes disabling a suggestion. `account_for` refuses a disabled account here exactly as
    it does on every reader route.

    The order matters for what an operator is told. "Your account is switched off" and "you
    are not an administrator" are different problems with different next steps, and
    collapsing them into one 403 sends somebody to argue about permissions when the answer
    is that they were disabled an hour ago.
    """
    account_for(service, identity)
    try:
        PolicyEngine().require(identity, ACCOUNT_MANAGE)
    except AuthorizationError as denial:
        # 403 rather than 404: an operator who is not an admin should learn that the
        # endpoint exists and that they may not use it, which is a different problem from
        # a typo in a URL.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"reason": "account_management_not_permitted", "detail": str(denial)},
        ) from denial


@admin_router.get("/v1/admin/accounts/{auth_subject:path}", response_model=AccountView)
def find_account(
    auth_subject: str,
    identity: IdentityDependency,
    service: AccountServiceDependency,
    store: Annotated[AccountStore, Depends(get_account_store)],
) -> AccountView:
    """Look an account up by the subject an operator actually has.

    By subject, not by id: what arrives with an incident is "this login is compromised",
    and an operator who has to translate that into a UUID before they can act has been
    given a step to get wrong at three in the morning.
    """
    _require_admin(identity, service)
    account = store.get_account_by_subject(auth_subject)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found")
    return _account_view(account)


@admin_router.post("/v1/admin/accounts/{account_id}/status", response_model=AccountView)
def set_account_status(
    account_id: UUID,
    body: AccountStatusChange,
    identity: IdentityDependency,
    service: AccountServiceDependency,
    store: Annotated[AccountStore, Depends(get_account_store)],
) -> AccountView:
    """Switch an account off, or back on. Audited, reasoned, and never on yourself."""
    _require_admin(identity, service)
    target = store.get_account(account_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found")

    if target.auth_subject == identity.subject and body.status == AccountStatus.DISABLED.value:
        # The role that would have to undo this is the one being switched off. Deployments
        # ship with one admin more often than they ship with two.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "cannot_disable_your_own_account",
                "detail": (
                    "disabling the account you are signed in with would lock out the role "
                    "needed to re-enable it; ask another administrator"
                ),
            },
        )

    try:
        changed = (
            service.disable(identity, account_id, body.reason)
            if body.status == AccountStatus.DISABLED.value
            else service.enable(identity, account_id, body.reason)
        )
    except AccountNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="account not found"
        ) from missing
    except ValueError as refusal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(refusal)
        ) from refusal
    return _account_view(changed)


@admin_router.get("/v1/admin/accounts", response_model=list[AccountView])
def list_accounts(
    identity: IdentityDependency,
    service: AccountServiceDependency,
    store: Annotated[AccountStore, Depends(get_account_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    *,
    disabled_only: bool = False,
) -> list[AccountView]:
    """Who exists, so an operator can find the one they were told about.

    `disabled_only` answers the question asked after an incident — "is it actually off" —
    without reading every account to find out.
    """
    _require_admin(identity, service)
    accounts, _has_more = store.list_accounts(
        limit=limit, offset=offset, disabled_only=disabled_only
    )
    return [_account_view(account) for account in accounts]


__all__ = ["AccountService", "admin_router"]
