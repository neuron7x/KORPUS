from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from korpus.application.offline_pack import OfflinePackLimitError, OfflinePackService
from korpus.application.policy import AuthorizationError, UnauthorizedCorporaError
from korpus.domain.models import CORPUS_ID_PATTERN, Identity
from korpus.security.auth import get_identity

router = APIRouter()
IdentityDependency = Annotated[Identity, Depends(get_identity)]


def get_offline_pack_service(request: Request) -> OfflinePackService | None:
    return cast(OfflinePackService | None, request.app.state.offline_pack_service)


class OfflinePackRequest(BaseModel):
    corpora: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("corpora")
    @classmethod
    def validate_corpora(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate corpus identifier")
        if any(not CORPUS_ID_PATTERN.fullmatch(value) for value in normalized):
            raise ValueError("invalid corpus identifier")
        return normalized


@router.post("/v1/offline-pack")
def export_offline_pack(
    request: OfflinePackRequest,
    identity: IdentityDependency,
    service: Annotated[OfflinePackService | None, Depends(get_offline_pack_service)],
) -> dict[str, object]:
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="offline pack export is disabled",
        )
    try:
        return service.export(identity, request.corpora)
    except UnauthorizedCorporaError as exc:
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
    except OfflinePackLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc


@router.get("/v1/offline-pack/key")
def offline_pack_key(
    identity: IdentityDependency,
    service: Annotated[OfflinePackService | None, Depends(get_offline_pack_service)],
) -> dict[str, str]:
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="offline pack export is disabled",
        )
    return {
        "algorithm": "Ed25519",
        "key_id": service.signer.key_id,
        "public_key_b64": service.signer.public_key_b64,
    }
