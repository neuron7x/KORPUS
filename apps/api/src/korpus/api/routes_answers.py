from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from korpus.api.answering import bounded_answer, overloaded
from korpus.api.dependencies import (
    get_admission_controller,
    get_answer_service,
    get_observability,
    get_policy,
    get_repository,
)
from korpus.application.answer_query import ExtractiveAnswerService
from korpus.application.policy import (
    AuthorizationError,
    PolicyEngine,
    UnauthorizedCorporaError,
)
from korpus.application.resilience import AdmissionController, OverloadedError
from korpus.domain.models import (
    Answer,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    QueryRequest,
)
from korpus.infrastructure.observability import Observability
from korpus.infrastructure.repository import SqlRepository
from korpus.security.auth import get_identity


router = APIRouter()
IdentityDependency = Annotated[Identity, Depends(get_identity)]


@router.post("/v1/answers", response_model=Answer)
def create_answer(
    query: QueryRequest,
    identity: IdentityDependency,
    service: Annotated[ExtractiveAnswerService, Depends(get_answer_service)],
    admission: Annotated[AdmissionController, Depends(get_admission_controller)],
    observability: Annotated[Observability, Depends(get_observability)],
) -> Answer:
    """The stateless door. The conversation route is the other one; both bound the same.

    The body of this used to live here, which is how the second door came to be written
    without it. See `korpus.api.answering`.
    """
    try:
        return bounded_answer(service, identity, query, admission, observability)
    except OverloadedError as exc:
        raise overloaded(exc) from exc
    except UnauthorizedCorporaError as exc:
        # Typed, and in the order the reader asked: a refusal that does not say which
        # corpus was refused cannot be acted on by the reader or by an operator.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "reason": exc.reason,
                "denied_corpora": exc.denied,
                "requested_corpora": exc.requested,
            },
        ) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

class DisclosedSpan(BaseModel):
    """One passage, addressed the way a reader can check it against the source.

    `text_hash` is over the span's own text, which is what makes the citation chain
    non-tautological: `quote_hash` proves the quote matches itself, and only the span
    ties the quote to the document that `source_hash` covers.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    version_id: UUID
    document_id: UUID
    document_title: str
    revision: str
    ordinal: int
    page: int | None
    section: str | None
    text: str
    text_hash: str
    source_hash: str
    source_uri: str | None

    @classmethod
    def build(
        cls,
        span: EvidenceSpanRecord,
        document: DocumentRecord,
        version: DocumentVersionRecord,
    ) -> DisclosedSpan:
        return cls(
            id=span.id,
            version_id=version.id,
            document_id=document.id,
            document_title=document.canonical_title,
            revision=version.revision,
            ordinal=span.ordinal,
            page=span.page,
            section=span.section,
            text=span.text,
            text_hash=span.text_hash,
            source_hash=version.source_hash,
            source_uri=version.source_uri,
        )


@router.get("/v1/document-versions/{version_id}/spans", response_model=list[DisclosedSpan])
def list_version_spans(
    identity: IdentityDependency,
    repository: Annotated[SqlRepository, Depends(get_repository)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
    version_id: UUID,
    as_of: Annotated[date | None, Query()] = None,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[DisclosedSpan]:
    """The passages of one version, so a citation has somewhere to point.

    Answers out of the same projection retrieval uses, so a reader can reach exactly
    the material an answer could have cited them and nothing else — on the date they
    ask about, since which edition governs is a function of that date.
    """

    try:
        policy.require(identity, "document:list")
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    effective = as_of or datetime.now(UTC).date()
    rows = repository.list_retrievable_spans(
        identity, identity.corpora, effective, version_id=version_id
    )
    rows.sort(key=lambda row: row[0].ordinal)
    return [DisclosedSpan.build(*row) for row in rows[offset : offset + limit]]


@router.get("/v1/spans/{span_id}", response_model=DisclosedSpan)
def read_span(
    identity: IdentityDependency,
    repository: Annotated[SqlRepository, Depends(get_repository)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
    span_id: UUID,
    as_of: Annotated[date | None, Query()] = None,
) -> DisclosedSpan:
    """One passage by id. 404 covers both "no such span" and "not yours".

    They are deliberately the same answer: distinguishing them would tell a reader that
    material they may not see exists, which is the disclosure the tier is for.
    """

    try:
        policy.require(identity, "document:list")
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    effective = as_of or datetime.now(UTC).date()
    rows = repository.get_retrievable_spans_by_ids(
        identity, identity.corpora, effective, [span_id]
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="span not found")
    return DisclosedSpan.build(*rows[0])
