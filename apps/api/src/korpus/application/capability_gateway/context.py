from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from korpus import __version__
from korpus.application.capability_gateway.contracts import payload_digest
from korpus.application.capability_gateway.types import (
    ActorType,
    CapabilitySpec,
    InvocationActor,
    InvocationContext,
)
from korpus.application.request_audit_context import current_request_audit_context
from korpus.domain.models import Identity


def policy_context_digest(
    identity: Identity,
    spec: CapabilitySpec,
    *,
    logical_resource: str | None = None,
) -> str:
    """Digest trusted server-side inputs that determine capability authorization."""

    return payload_digest(
        {
            "subject": identity.subject,
            "roles": sorted(identity.roles),
            "clearance": int(identity.clearance),
            "corpora": sorted(identity.corpora),
            "compartments": sorted(identity.compartments),
            "capability_id": spec.capability_id,
            "capability_version": spec.version,
            "action": spec.authorization.action,
            "resource_mapper": spec.authorization.resource_mapper,
            "logical_resource": logical_resource,
            "effect_class": spec.effect_class.value,
        }
    )


def build_invocation_context(
    *,
    identity: Identity,
    spec: CapabilitySpec,
    actor_type: ActorType = ActorType.USER,
    purpose: str | None = None,
    trace_id: str | None = None,
    request_time: datetime | None = None,
) -> InvocationContext:
    request_context = current_request_audit_context()
    return InvocationContext(
        schema_version="korpus.invocation-context.v1",
        invocation_id=uuid4(),
        actor=InvocationActor(
            actor_type=actor_type,
            subject_id=identity.subject,
            session_binding=request_context.session_binding,
        ),
        request_time=request_time or datetime.now(UTC),
        service_release=__version__,
        policy_context_digest=policy_context_digest(identity, spec),
        trace_id=trace_id,
        purpose=purpose,
    )


def bind_invocation_resource(
    context: InvocationContext,
    *,
    identity: Identity,
    spec: CapabilitySpec,
    logical_resource: str,
) -> InvocationContext:
    """Bind the already-created invocation identity to its server-derived resource."""

    resource = logical_resource.strip()
    if not resource:
        raise ValueError("logical resource must be non-empty")
    return context.model_copy(
        update={
            "policy_context_digest": policy_context_digest(
                identity,
                spec,
                logical_resource=resource,
            )
        }
    )
