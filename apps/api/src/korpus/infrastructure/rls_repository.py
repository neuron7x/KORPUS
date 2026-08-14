from __future__ import annotations

import json
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.pool import NullPool

from korpus.domain.models import Identity
from korpus.infrastructure.repository import SqlRepository


class RlsBoundSqlRepository(SqlRepository):
    """SqlRepository whose PostgreSQL RLS context is committed by a separate login."""

    def __init__(
        self,
        database_url: str,
        audit_hmac_key: str,
        *args: Any,
        authz_database_url: str | None = None,
        review_database_url: str | None = None,
        connect_timeout_seconds: int = 5,
        statement_timeout_ms: int = 30_000,
        lock_timeout_ms: int = 5_000,
        **kwargs: Any,
    ) -> None:
        self._authz_url = authz_database_url
        if database_url.startswith("postgresql"):
            self._validate_authz_url(database_url, review_database_url, authz_database_url)
        super().__init__(
            database_url,
            audit_hmac_key,
            *args,
            review_database_url=review_database_url,
            connect_timeout_seconds=connect_timeout_seconds,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
            **kwargs,
        )
        self.authz_engine: Engine | None = None
        if database_url.startswith("postgresql"):
            self.authz_engine = create_engine(
                authz_database_url or "",
                future=True,
                pool_pre_ping=True,
                poolclass=NullPool,
                connect_args={
                    "connect_timeout": connect_timeout_seconds,
                    "options": (
                        f"-c statement_timeout={statement_timeout_ms} "
                        f"-c lock_timeout={lock_timeout_ms}"
                    ),
                },
            )

    @staticmethod
    def _validate_authz_url(
        database_url: str,
        review_database_url: str | None,
        authz_database_url: str | None,
    ) -> None:
        if not authz_database_url:
            raise ValueError("PostgreSQL RLS requires a separate authz database identity")
        primary = make_url(database_url)
        authz = make_url(authz_database_url)
        primary_target = (primary.get_backend_name(), primary.host, primary.port, primary.database)
        authz_target = (authz.get_backend_name(), authz.host, authz.port, authz.database)
        if authz_target != primary_target or authz.get_backend_name() != "postgresql":
            raise ValueError("authz database identity must target the primary PostgreSQL database")
        if not authz.username or authz.username == primary.username:
            raise ValueError("authz database identity must use a distinct PostgreSQL login")
        if review_database_url:
            review = make_url(review_database_url)
            if authz.username == review.username:
                raise ValueError("authz and review database identities must use distinct logins")

    def _apply_postgres_identity(self, connection: Connection, identity: Identity) -> None:
        if connection.dialect.name != "postgresql":
            return
        if self.authz_engine is None:
            raise RuntimeError("PostgreSQL RLS authorization broker is unavailable")
        target = connection.execute(
            text(
                "SELECT pg_catalog.pg_backend_pid() AS backend_pid, "
                "pg_catalog.txid_current() AS transaction_id, session_user::text AS session_login"
            )
        ).one()
        classifications = sorted(self._allowed_classifications(identity.clearance))
        parameters = {
            "backend_pid": int(target.backend_pid),
            "transaction_id": int(target.transaction_id),
            "session_login": str(target.session_login),
            "clearance": int(identity.clearance),
            "corpora": json.dumps(sorted(identity.corpora), separators=(",", ":")),
            "classifications": json.dumps(classifications, separators=(",", ":")),
            "compartments": json.dumps(sorted(identity.compartments), separators=(",", ":")),
            "roles": json.dumps(sorted(identity.roles), separators=(",", ":")),
        }
        with self.authz_engine.begin() as broker:
            broker.execute(
                text(
                    "SELECT public.korpus_bind_rls_context("
                    ":backend_pid, :transaction_id, CAST(:session_login AS name), :clearance, "
                    "CAST(:corpora AS jsonb), CAST(:classifications AS jsonb), "
                    "CAST(:compartments AS jsonb), CAST(:roles AS jsonb))"
                ),
                parameters,
            )

    def close(self) -> None:
        if self.authz_engine is not None:
            self.authz_engine.dispose()
        super().close()
