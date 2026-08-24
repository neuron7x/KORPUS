from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from korpus.api.dependencies import get_object_store, get_observability, get_repository
from korpus.api.readiness_projection import success_payload
from korpus.application.ports import ObjectStore
from korpus.config import Settings, get_settings
from korpus.domain.models import Identity
from korpus.infrastructure.observability import Observability
from korpus.infrastructure.repository import SqlRepository
from korpus.security.auth import get_identity

router = APIRouter()
IdentityDependency = Annotated[Identity, Depends(get_identity)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _readiness_detail_permitted(settings: Settings, authorization: str | None) -> bool:
    """Whether this caller may see the internal readiness snapshot.

    The snapshot names the audit head hash, the schema revision and the anchor backlog —
    a reconnaissance surface. It is gated exactly as `/metrics` is: open when no metrics
    token is configured (a local box the operator has not locked down), and behind that
    token once one exists. A public deployment sets the token, so a soldier or an
    onlooker catching the service mid-degradation sees a word, not the internals.
    """
    expected = settings.resolved_metrics_token
    if expected is None:
        return True
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    return hmac.compare_digest(supplied, expected)


@router.get("/ready")
def ready(
    repository: Annotated[SqlRepository, Depends(get_repository)],
    object_store: Annotated[ObjectStore, Depends(get_object_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    observability: Annotated[Observability | None, Depends(get_observability)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    detail_permitted = _readiness_detail_permitted(settings, authorization)
    try:
        snapshot = repository.readiness_snapshot(
            max_pending_events=settings.audit_max_pending_events,
            max_pending_age_seconds=settings.audit_max_pending_age_seconds,
        )
        object_store_ok = object_store.healthcheck()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"ready": False, "reason": type(exc).__name__},
        ) from exc
    schema_ok = (
        snapshot["schema_revision"] == snapshot["expected_schema_revision"]
        if settings.schema_mode == "migrations"
        else True
    )
    is_ready = bool(snapshot["ready"] and object_store_ok and schema_ok)
    # Reported, not gated. Telemetry display may degrade under the release policy as
    # long as the underlying event stays durably available, and it does — the audit
    # chain is not the tracer. What must not happen is an operator reading
    # `otlp_endpoint` in the config and believing traces exist when the exporter was
    # never attached.
    # The status word only. /ready is unauthenticated, and the OTLP endpoint is an
    # internal address: test_health_and_readiness_are_operational_not_information_side
    # _channels exists precisely to keep infrastructure detail out of this response.
    telemetry = (
        str(observability.telemetry_status()["traces"]) if observability is not None else "UNKNOWN"
    )
    payload = {
        **snapshot,
        "object_store": object_store_ok,
        "schema_current": schema_ok,
        "telemetry": telemetry,
        "ready": is_ready,
    }
    if not is_ready:
        # The full snapshot is a reconnaissance surface, so an unauthenticated caller gets
        # only the reason word. `not_ready` is the fallback rather than a leak: the three
        # named conditions are the ones an operator with the token can then read in full.
        if not detail_permitted:
            reason = (
                "object_store"
                if not object_store_ok
                else "schema"
                if not schema_ok
                else "audit_backlog"
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"ready": False, "reason": reason},
            )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=payload)
    return success_payload(
        detail_permitted=detail_permitted, snapshot=snapshot, telemetry=telemetry
    )


@router.get("/metrics", include_in_schema=False)
def metrics(
    settings: Annotated[Settings, Depends(get_settings)],
    observability: Annotated[Observability, Depends(get_observability)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="metrics disabled")
    expected = settings.resolved_metrics_token
    if expected is not None:
        supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="metrics authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return Response(observability.export_prometheus(), media_type="text/plain; version=0.0.4")
