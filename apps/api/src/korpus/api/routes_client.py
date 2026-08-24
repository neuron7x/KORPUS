"""Authenticated browser bootstrap route."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from korpus.api.dependencies import get_policy
from korpus.application.client_bootstrap import ClientBootstrap, build_client_bootstrap
from korpus.application.policy import PolicyEngine
from korpus.config import Settings, get_settings
from korpus.domain.models import Identity
from korpus.security.auth import get_identity

router = APIRouter()


@router.get("/v1/client/bootstrap", response_model=ClientBootstrap)
def client_bootstrap(
    identity: Annotated[Identity, Depends(get_identity)],
    settings: Annotated[Settings, Depends(get_settings)],
    policy: Annotated[PolicyEngine, Depends(get_policy)],
) -> ClientBootstrap:
    return build_client_bootstrap(identity, settings, policy)
