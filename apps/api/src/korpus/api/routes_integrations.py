from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Response, status

from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.invoke import IntegrationResult
from korpus.application.capability_gateway.types import IntegrationRequest
from korpus.domain.models import Identity
from korpus.security.auth import get_identity


class CapabilityInvoker(Protocol):
    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult: ...


_PREAUTH_DENIALS = frozenset({"CAPABILITY_UNKNOWN", "CAPABILITY_DISABLED", "POLICY_DENIED"})


def public_integration_result(result: IntegrationResult) -> IntegrationResult:
    """Project precise internal decisions into a non-oracular client envelope."""

    if result.error_code in _PREAUTH_DENIALS:
        return result.model_copy(update={"error_code": "CAPABILITY_UNAVAILABLE"})
    if result.outcome is InvocationOutcome.FAILED:
        # Internal adapter/schema/audit topology is operator evidence, not client data.
        return result.model_copy(
            update={"output": None, "evidence": None, "error_code": "INTEGRATION_FAILED"}
        )
    return result


def build_integration_router(invoker: CapabilityInvoker) -> APIRouter:
    """Create the API surface without activating it in the application composition root."""

    router = APIRouter()
    identity_dependency = Annotated[Identity, Depends(get_identity)]

    @router.post("/v1/integrations/invoke", response_model=IntegrationResult)
    def invoke_capability(
        request: IntegrationRequest,
        identity: identity_dependency,
        response: Response,
    ) -> IntegrationResult:
        internal = invoker.invoke(identity=identity, request=request)
        public = public_integration_result(internal)
        if internal.error_code in _PREAUTH_DENIALS:
            response.status_code = status.HTTP_404_NOT_FOUND
        elif public.outcome is InvocationOutcome.DENIED:
            response.status_code = status.HTTP_403_FORBIDDEN
        elif public.outcome is InvocationOutcome.REJECTED:
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        elif public.outcome is InvocationOutcome.FAILED:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif public.outcome is InvocationOutcome.ABSTAINED:
            response.status_code = status.HTTP_409_CONFLICT
        elif public.outcome is InvocationOutcome.OUTCOME_UNKNOWN:
            # A retry can duplicate an already-committed effect. 409 forces the caller
            # into explicit reconciliation rather than treating the transport as failed.
            response.status_code = status.HTTP_409_CONFLICT
        return public

    return router
