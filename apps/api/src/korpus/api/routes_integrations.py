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
_PUBLIC_PREAUTH_ERROR = "CAPABILITY_UNAVAILABLE"


def _failed_public_result(invocation_id: object = None) -> IntegrationResult:
    return IntegrationResult(
        invocation_id=invocation_id if isinstance(invocation_id, UUID) else uuid4(),
        outcome=InvocationOutcome.FAILED,
        error_code="INTEGRATION_FAILED",
    )


def _revalidate_public_result(result: IntegrationResult) -> IntegrationResult:
    """Re-establish result invariants at the transport trust boundary.

    `model_construct`, deserialization bugs or a regressed internal invoker can bypass normal
    Pydantic construction. HTTP must not trust object identity as proof that SUCCESS carries
    a persisted audit id or that non-success payload constraints still hold.
    """

    try:
        return IntegrationResult.model_validate(result.model_dump(mode="python"))
    except Exception:
        return _failed_public_result(result.invocation_id)


def public_integration_result(result: object) -> IntegrationResult:
    """Project an untrusted internal return value into the public result contract.

    Runtime protocol conformance is checked explicitly: Python type hints cannot prove that a
    regressed or compromised invoker returned `IntegrationResult`. Invalid objects collapse to
    one stable failed envelope before status projection or payload exposure.
    """

    if not isinstance(result, IntegrationResult):
        return _failed_public_result()
    if result.outcome is InvocationOutcome.SUCCESS:
        return _revalidate_public_result(result)

    updates: dict[str, object | None] = {"output": None, "evidence": None}
    if result.error_code in _PREAUTH_DENIALS:
        updates["error_code"] = _PUBLIC_PREAUTH_ERROR
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
        # Status projection consumes only the revalidated public envelope. The internal object
        # is not authority at this boundary, even when its static type claims otherwise.
        if public.error_code == _PUBLIC_PREAUTH_ERROR:
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
