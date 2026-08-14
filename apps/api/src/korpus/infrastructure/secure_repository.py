from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Connection

from korpus.application.keyring import AuditKeyRing
from korpus.application.policy import PolicyEngine
from korpus.domain.models import Identity
from korpus.infrastructure.audit_anchor import AuditAnchorStore
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.rls_identity import RlsIdentityBinder


class RlsBoundSqlRepository(SqlRepository):
    """SqlRepository whose PostgreSQL authorization claims cannot be SET by its DB login."""

    def __init__(
        self,
        database_url: str,
        audit_hmac_key: str,
        policy: PolicyEngine | None = None,
        audit_anchor_path: Path | None = None,
        audit_anchor_store: AuditAnchorStore | None = None,
        *,
        pool_size: int = 8,
        max_overflow: int = 8,
        pool_timeout_seconds: float = 10.0,
        pool_recycle_seconds: int = 1800,
        connect_timeout_seconds: int = 5,
        statement_timeout_ms: int = 30_000,
        lock_timeout_ms: int = 5_000,
        audit_keyring: AuditKeyRing | None = None,
        review_database_url: str | None = None,
        rls_identity_database_url: str | None = None,
    ) -> None:
        super().__init__(
            database_url,
            audit_hmac_key,
            policy,
            audit_anchor_path,
            audit_anchor_store,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout_seconds=pool_timeout_seconds,
            pool_recycle_seconds=pool_recycle_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
            audit_keyring=audit_keyring,
            review_database_url=review_database_url,
        )
        identity_url = rls_identity_database_url or os.getenv("RLS_IDENTITY_DATABASE_URL")
        broker_options: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        try:
            self._rls_identity = RlsIdentityBinder(
                database_url,
                identity_url,
                broker_options,
                review_database_url=review_database_url,
            )
        except Exception:
            super().close()
            raise

    def _apply_postgres_identity(self, connection: Connection, identity: Identity) -> None:
        self._rls_identity.bind(connection, identity)

    def close(self) -> None:
        try:
            self._rls_identity.close()
        finally:
            super().close()
