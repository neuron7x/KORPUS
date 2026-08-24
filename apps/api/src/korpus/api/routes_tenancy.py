"""Account and conversation endpoints, and the seams the billing routes share.

A separate router from `routes.py` because these are the product around the answer kernel
and that file is the kernel. The commercial edge — plans, subscriptions, the provider
webhook — is one file further out in `routes_billing.py`, which imports the account
resolution from here rather than repeating it.

Three rules hold across every route here:

  the account is derived, never sent
      `account_for` resolves it from the authenticated identity. A request body naming an
      `account_id` would be a client asserting whose data it wants, which is the whole of
      a broken-object-level-authorization bug.

  disabled is refused before work starts
      `require_active_account` runs first in every handler, so a disabled account cannot
      reach retrieval, a model, or another account's conversation.

  a subscription decides *whether*, never *what*
      the entitlement is intersected with what the policy engine already permits. See
      `korpus.application.paid_access`.
"""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from korpus.api.answering import bounded_answer, overloaded
from korpus.api.dependencies import (
    get_admission_controller,
    get_answer_service,
    get_observability,
    get_repository,
)
from korpus.application.accounts import AccountService
from korpus.application.answer_query import ExtractiveAnswerService
from korpus.application.conversations import ConversationLimitReached, ConversationService
from korpus.application.paid_access import EntitlementDenied, EntitlementProjection
from korpus.application.policy import AuthorizationError, UnauthorizedCorporaError
from korpus.application.resilience import AdmissionController, OverloadedError
from korpus.application.tenancy_ports import (
    AccountDisabled,
    AccountStore,
    ConversationArchived,
    ConversationNotFound,
)
from korpus.domain.models import Answer, Identity, QueryRequest
from korpus.domain.tenancy import AccountRecord, ConversationRecord, MessageRecord
from korpus.infrastructure.observability import Observability
from korpus.infrastructure.repository import SqlRepository
from korpus.security.auth import get_identity

tenancy_router = APIRouter()
IdentityDependency = Annotated[Identity, Depends(get_identity)]


def _state(request: Request, name: str) -> Any:
    value = getattr(request.app.state, name, None)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{name.replace('_', ' ')} is not configured in this deployment",
        )
    return value


def get_account_service(request: Request) -> AccountService:
    service: AccountService = _state(request, "account_service")
    return service


def get_conversation_service(request: Request) -> ConversationService:
    service: ConversationService = _state(request, "conversation_service")
    return service


def get_entitlements(request: Request) -> EntitlementProjection:
    projection: EntitlementProjection = _state(request, "entitlements")
    return projection


def get_account_store(request: Request) -> AccountStore:
    return cast(AccountStore, _state(request, "account_store"))


AccountServiceDependency = Annotated[AccountService, Depends(get_account_service)]
ConversationServiceDependency = Annotated[ConversationService, Depends(get_conversation_service)]
EntitlementDependency = Annotated[EntitlementProjection, Depends(get_entitlements)]


def account_for(service: AccountService, identity: Identity) -> AccountRecord:
    """The account behind this request, refusing if it is disabled.

    Every handler starts here. The account is never taken from the request body: a client
    naming the account it wants is a client choosing whose data to read.
    """
    try:
        return service.require_active_account(identity)
    except AccountDisabled as denial:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"reason": denial.reason, "account_id": str(denial)},
        ) from denial


class AccountView(BaseModel):
    """What the account is, with nothing about what it may read.

    Deliberately carries no roles, clearance, corpora or compartments. A client that
    received them would render them, and a client that renders an authorization decision
    is a client somebody eventually trusts to make one.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    auth_subject: str
    email: str | None
    display_name: str | None
    status: str
    created_at: str


class ConversationView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    title: str | None
    created_at: str
    updated_at: str
    archived: bool


class MessageView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    role: str
    text: str
    answer_id: UUID | None
    #: The verdict the reader was shown. `null` for a turn stored before it was recorded,
    #: which the interface renders as unrecorded rather than as an answer.
    answer_status: str | None
    created_at: str


class ConversationPageView(BaseModel):
    """A page of conversations, and whether it is the whole list.

    An envelope rather than a bare array, which is what this returned until a reader with
    more than fifty conversations would have seen fifty and been told nothing. A list
    endpoint that cannot say "there is more" reports a truncation as a fact about the
    account.
    """

    model_config = ConfigDict(frozen=True)

    items: list[ConversationView]
    has_more: bool
    next_offset: int | None


class MessagePageView(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[MessageView]
    has_more: bool
    next_offset: int | None


class CreateConversation(BaseModel):
    title: str | None = Field(default=None, max_length=200)


def _account_view(account: AccountRecord) -> AccountView:
    return AccountView(
        id=account.id,
        auth_subject=account.auth_subject,
        email=account.email,
        display_name=account.display_name,
        status=account.status.value,
        created_at=account.created_at.isoformat(),
    )


def _conversation_view(conversation: ConversationRecord) -> ConversationView:
    return ConversationView(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
        archived=conversation.archived_at is not None,
    )


def _message_view(message: MessageRecord) -> MessageView:
    return MessageView(
        id=message.id,
        role=message.role.value,
        text=message.raw_text,
        answer_id=message.answer_id,
        answer_status=message.answer_status,
        created_at=message.created_at.isoformat(),
    )


# --------------------------------------------------------------------- account


@tenancy_router.get("/v1/account", response_model=AccountView)
def read_account(identity: IdentityDependency, service: AccountServiceDependency) -> AccountView:
    """The caller's own account, created on first sight.

    There is no registration step. A person who authenticates has an account by the time
    this returns, which is what makes first login idempotent rather than a form somebody
    can submit twice.
    """
    return _account_view(account_for(service, identity))


# --------------------------------------------------------------- conversations


@tenancy_router.get("/v1/conversations", response_model=ConversationPageView)
def list_conversations(
    identity: IdentityDependency,
    service: AccountServiceDependency,
    conversations: ConversationServiceDependency,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    # Keyword-only. A query parameter is bound by name here anyway; the annotation exists
    # so the architecture gate's rule — a boolean nobody can pass positionally — holds
    # uniformly rather than having an exception for routing functions.
    *,
    include_archived: bool = False,
) -> ConversationPageView:
    account = account_for(service, identity)
    page = conversations.list_conversations(
        account, include_archived=include_archived, limit=limit, offset=offset
    )
    return ConversationPageView(
        items=[_conversation_view(item) for item in page.items],
        has_more=page.has_more,
        next_offset=page.next_offset,
    )


@tenancy_router.post(
    "/v1/conversations", response_model=ConversationView, status_code=status.HTTP_201_CREATED
)
def create_conversation(
    body: CreateConversation,
    identity: IdentityDependency,
    service: AccountServiceDependency,
    conversations: ConversationServiceDependency,
) -> ConversationView:
    account = account_for(service, identity)
    return _conversation_view(conversations.create(account, body.title))


@tenancy_router.get("/v1/conversations/{conversation_id}", response_model=MessagePageView)
def read_conversation(
    conversation_id: UUID,
    identity: IdentityDependency,
    service: AccountServiceDependency,
    conversations: ConversationServiceDependency,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> MessagePageView:
    account = account_for(service, identity)
    try:
        page = conversations.messages(account, conversation_id, limit=limit, offset=offset)
        return MessagePageView(
            items=[_message_view(message) for message in page.items],
            has_more=page.has_more,
            next_offset=page.next_offset,
        )
    except ConversationNotFound as missing:
        # The same 404 whether it does not exist or belongs to somebody else. Telling an
        # unauthorized caller that the id is real is half of what enumeration needs.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found"
        ) from missing


@tenancy_router.post("/v1/conversations/{conversation_id}/archive", response_model=ConversationView)
def archive_conversation(
    conversation_id: UUID,
    identity: IdentityDependency,
    service: AccountServiceDependency,
    conversations: ConversationServiceDependency,
) -> ConversationView:
    account = account_for(service, identity)
    try:
        return _conversation_view(conversations.archive(account, conversation_id))
    except ConversationNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found"
        ) from missing
    except ConversationArchived as already:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="conversation is already archived"
        ) from already


@tenancy_router.post("/v1/conversations/{conversation_id}/ask", response_model=Answer)
async def ask_within_conversation(
    conversation_id: UUID,
    query: QueryRequest,
    identity: IdentityDependency,
    service: AccountServiceDependency,
    conversations: ConversationServiceDependency,
    entitlements: EntitlementDependency,
    answers: Annotated[ExtractiveAnswerService, Depends(get_answer_service)],
    admission: Annotated[AdmissionController, Depends(get_admission_controller)],
    repository: Annotated[SqlRepository, Depends(get_repository)],
    observability: Annotated[Observability, Depends(get_observability)],
) -> Answer:
    """One question inside a conversation.

    The order is the point. Account, then conversation ownership, then entitlement — all
    of it before `execute`, which is the expensive call: retrieval over a hundred thousand
    spans, a possible model round trip, and an audit append. Checking payment afterwards
    would mean an unpaid request costs exactly as much as a paid one, which is how a
    paywall becomes a denial-of-service amplifier.

    The stored history never re-enters retrieval. The question that is answered is the
    question that was asked, and the previous turns are not appended to it: a system that
    fed its own prior answers back in as context would be citing itself within three
    turns.
    """
    account = account_for(service, identity)
    try:
        conversations.get(account, conversation_id)
    except ConversationNotFound as missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found"
        ) from missing

    try:
        permitted = entitlements.authorize_corpora(identity, account, list(query.corpus_ids))
    except EntitlementDenied as denial:
        repository.append_audit(
            identity,
            "answer.entitlement_denied",
            "account",
            str(account.id),
            entitlements.account_denial(account.id, denial.reason),
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"reason": denial.reason, "detail": str(denial)},
        ) from denial
    except UnauthorizedCorporaError as denial:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "reason": denial.reason,
                "denied_corpora": denial.denied,
                "requested_corpora": denial.requested,
            },
        ) from denial
    except AuthorizationError as denial:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(denial)) from denial

    try:
        conversations.record_question(account, conversation_id, query.text)
    except ConversationLimitReached as full:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(full)) from full
    except ConversationArchived as archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="conversation is archived"
        ) from archived

    scoped = query.model_copy(update={"corpus_ids": sorted(permitted)})
    # The same bound the stateless route uses. It was missing here until a re-audit found
    # it: the conversation route became the browser's default the moment the interface had
    # a conversation panel, so the per-subject share that stops one account saturating
    # retrieval was, in practice, off — while `/v1/answers` still had it and the gate
    # still read green.
    try:
        answer = await run_in_threadpool(
            bounded_answer, answers, identity, scoped, admission, observability
        )
    except OverloadedError as exc:
        raise overloaded(exc) from exc

    conversations.record_answer(
        account, conversation_id, answer.text, answer.id, answer.status.value
    )
    return answer
