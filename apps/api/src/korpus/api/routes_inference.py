"""Authenticated, non-secret status of the optional inference seam."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from korpus.api.dependencies import get_policy
from korpus.application.policy import AuthorizationError, PolicyEngine
from korpus.config import Settings, get_settings
from korpus.domain.models import Identity
from korpus.model_settings import resolved_model_api_key
from korpus.security.auth import get_identity

router = APIRouter()
IdentityDependency = Annotated[Identity, Depends(get_identity)]


class InferenceStatusView(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    provider: Literal["none", "anthropic", "openai"]
    model: str
    planner_enabled: bool
    composer_enabled: bool
    egress_posture: str
    egress_max_tier: str
    answer_authority: Literal["extractive_evidence"] = "extractive_evidence"
    openai_store: bool | None = None


@router.get("/v1/inference/status", response_model=InferenceStatusView)
def inference_status(
    identity: IdentityDependency,
    policy: Annotated[PolicyEngine, Depends(get_policy)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InferenceStatusView:
    """Expose inference posture without exposing keys, URLs or secret-file locations."""
    try:
        policy.require(identity, "answer:read")
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    planner = settings.query_planner_enabled and bool(resolved_model_api_key(settings))
    composer = settings.answer_composer_enabled and bool(resolved_model_api_key(settings))
    enabled = planner or composer
    provider = settings.query_planner_provider if enabled else "none"
    return InferenceStatusView(
        enabled=enabled,
        provider=provider,
        model=settings.query_planner_model if enabled else "",
        planner_enabled=planner,
        composer_enabled=composer,
        egress_posture=settings.model_egress_posture,
        egress_max_tier=settings.model_egress_max_tier,
        openai_store=False if enabled and provider == "openai" else None,
    )
