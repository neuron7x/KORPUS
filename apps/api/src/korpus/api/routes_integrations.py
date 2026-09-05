from __future__ import annotations

from typing import Annotated, Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Response, status

from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.invoke import IntegrationResult
from korpus.application.capability_gateway.types import IntegrationRequest
from korpus.domain.models import Identity
from korpus.security.auth import get_identity


class CapabilityInvoker(Protocol):
    def invoke(self, *, identity: Identity, request: IntegrationRequest) -> IntegrationResult: ...


IdentityDependency = Annotated[Identity, Depends(get_identity)]
_PREAUTH_DENIALS = frozenset({"CAPABILITY_UNKNOWN", "CAPABILITY_DISABLED", "POLICY_DENIED"})


def _revalidate_public_result(result: IntegrationResult) -> IntegrationResult:
    """Re-establish result invariants at the transport trust boundary.

    `model_construct`, deserialization bugs or a regressed internal invoker can bypass normal
    Pydantic construction. HTTP must not trust object identity as proof that SUCCESS carries
    a persisted audit id or that non-success payload constraints still hold.
    """

    try:
        return IntegrationResult.model_validate(result.model_dump(mode="python"))
    except Exception:
        invocation_id = result.invocation_id if isinstance(result.invocation_id, UUID) else uuid4()
        return IntegrationResult(
            invocation_id=invocation_id,
            outcome=InvocationOutcome.FAILED,
            error_code="INTEGRATION_FAILED",
        )


def public_integration_result(result: IntegrationResult) -> IntegrationResult:
    """Project precise internal decisions into a non-oracular client envelope.

    The application core already withholds output for non-success outcomes. This projection
    repeats that rule at the HTTP boundary so a future core regression cannot turn a denied,
    failed or ambiguous invocation into data disclosure. The projected envelope is then
    revalidated so an invalid SUCCESS cannot bypass the canonical audit-success invariant.
    """

    if result.outcome is InvocationOutcome.SUCCESS:
        return _revalidate_public_result(result)

    updates: dict[str, object | None] = {"output": None, "evidence": None}
    if result.error_code in _PREAUTH_DENIALS:
        updates["error_code"] = "CAPABILITY_UNAVAILABLE"
    elif result.outcome is InvocationOutcome.FAILED:
        # Internal adapter/schema/audit topology is operator evidence, not client data.
        updates["error_code"] = "INTEGRATION_FAILED"
    return _revalidate_public_result(result.model_copy(update=updates))


def build_integration_router(invoker: CapabilityInvoker) -> APIRouter:
    """Create the API surface without activating it in the application composition root."""

    router = APIRouter()

    @router.post("/v1/integrations/invoke", response_model=IntegrationResult)
    def invoke_capability(
        request: IntegrationRequest,
        identity: IdentityDependency,
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
            # 409 forces explicit state resolution before any retry. Depending on the
            # durable state this may mean wait/recovery or provider reconciliation.
            response.status_code = status.HTTP_409_CONFLICT
        return public

    return router
