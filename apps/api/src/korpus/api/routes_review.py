from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from korpus.api.dependencies import get_ingestion_service, get_policy, get_repository
from korpus.application.ingestion import IngestionService
from korpus.application.policy import PolicyEngine
from korpus.domain.models import (
    DocumentVersionRecord,
    Identity,
    RescissionRequest,
    ReviewTransition,
)
from korpus.infrastructure.repository import ConcurrentWriteError, SqlRepository
from korpus.security.auth import get_identity

router = APIRouter()
IdentityDependency = Annotated[Identity, Depends(get_identity)]


@router.post("/v1/document-versions/{version_id}/review", response_model=DocumentVersionRecord)
def review_version(
    version_id: UUID,
    transition: ReviewTransition,
    identity: IdentityDependency,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> DocumentVersionRecord:
    try:
        return service.transition(identity, version_id, transition)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConcurrentWriteError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/v1/document-versions/{version_id}/rescission", response_model=DocumentVersionRecord
)
def rescind_version(
    version_id: UUID,
    request_body: RescissionRequest,
    identity: IdentityDependency,
    repository: Annotated[SqlRepository, Depends(get_repository)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
) -> DocumentVersionRecord:
    """Take an approved version out of force from a date, without rewriting review state."""
    try:
        policy.require(identity, "document:approve")
        version = repository.get_version(identity, version_id)
        if version is None:
            raise LookupError("version not found")
        document = repository.get_document(identity, version.document_id)
        if document is None or not policy.can_access_document(identity, document).allowed:
            raise LookupError("version not found")
        return repository.rescind_version(
            identity,
            version_id,
            note=request_body.note,
            rescinded_at=request_body.rescinded_at,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ConcurrentWriteError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
