"""Bind trusted source visibility without treating authorization loss as revocation."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.engine import Connection

from korpus.application.policy import AuthorizationError, PolicyEngine
from korpus.domain.learning import BoundSourceState, CourseVersion
from korpus.domain.models import Identity
from korpus.infrastructure import row_mapping
from korpus.infrastructure.learning_source_state import load_bound_source_states
from korpus.infrastructure.schema import documents

type IdentityBinder = Callable[[Connection, Identity], None]


class LearningSourceAccess:
    """The binder comes from the runtime repository, identity from trusted authentication."""

    def __init__(self, bind_identity: IdentityBinder | None) -> None:
        self._bind_identity = bind_identity

    def bind(self, connection: Connection, identity: Identity | None) -> None:
        if connection.dialect.name == "postgresql":
            if identity is None or self._bind_identity is None:
                raise AuthorizationError("trusted learning source identity and binder are required")
            self._bind_identity(connection, identity)

    def load(
        self, connection: Connection, version: CourseVersion, identity: Identity | None
    ) -> dict[str, BoundSourceState]:
        states = load_bound_source_states(connection, version)
        if identity is not None:
            requested = {
                binding.version_id
                for module in version.modules
                for lesson in module.lessons
                for binding in lesson.source_bindings
            }
            if requested - states.keys():
                raise AuthorizationError("learning source is outside the authorized scope")
            self._authorize_documents(connection, states, identity)
        return states

    @staticmethod
    def _authorize_documents(
        connection: Connection, states: dict[str, BoundSourceState], identity: Identity
    ) -> None:
        requested = {state.document_id for state in states.values()}
        rows = (
            connection.execute(select(documents).where(documents.c.id.in_(sorted(requested))))
            .mappings()
            .all()
        )
        policy = PolicyEngine()
        visible = {
            str(row["id"])
            for row in rows
            if policy.can_access_document(identity, row_mapping.document(row)).allowed
        }
        if visible != requested:
            raise AuthorizationError("learning source is outside the authorized scope")
