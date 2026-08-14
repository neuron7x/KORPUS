from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url

from korpus.domain.models import Identity
from korpus.infrastructure.row_mapping import allowed_classifications


class RlsIdentityBindingError(RuntimeError):
    pass


def _database_target(url: str) -> tuple[str, str | None, int | None, str | None]:
    parsed = make_url(url)
    return parsed.get_backend_name(), parsed.host, parsed.port, parsed.database


def _database_user(url: str | None) -> str | None:
    return make_url(url).username if url else None


class RlsIdentityBinder:
    """Bind protected DB transactions to claims supplied by a separate broker login."""

    def __init__(
        self,
        primary_database_url: str,
        identity_database_url: str | None,
        engine_options: dict[str, Any],
        *,
        review_database_url: str | None = None,
    ) -> None:
        self.engine: Engine | None = None
        if not primary_database_url.startswith("postgresql"):
            if identity_database_url:
                raise ValueError("RLS identity database login is valid only with PostgreSQL")
            return
        if not identity_database_url:
            return
        if _database_target(primary_database_url) != _database_target(identity_database_url):
            raise ValueError("RLS identity login must target the primary PostgreSQL database")
        identity_user = _database_user(identity_database_url)
        protected_users = {
            _database_user(primary_database_url),
            _database_user(review_database_url),
        }
        protected_users.discard(None)
        if not identity_user or identity_user in protected_users:
            raise ValueError("RLS identity login must be distinct from protected PostgreSQL logins")
        self.engine = create_engine(identity_database_url, **engine_options)

    def bind(self, connection: Connection, identity: Identity) -> None:
        if connection.dialect.name != "postgresql":
            return
        if self.engine is None:
            raise RlsIdentityBindingError("PostgreSQL RLS identity broker is unavailable")
        isolation = str(
            connection.execute(text("SHOW transaction_isolation")).scalar_one()
        ).lower()
        if isolation != "read committed":
            raise RlsIdentityBindingError(
                "RLS identity broker requires READ COMMITTED transaction isolation"
            )
        row = connection.execute(
            text(
                "SELECT pg_catalog.pg_backend_pid(), a.backend_start, "
                "pg_catalog.pg_current_xact_id()::text, session_user "
                "FROM pg_catalog.pg_stat_activity a "
                "WHERE a.pid = pg_catalog.pg_backend_pid()"
            )
        ).one()
        backend_pid, backend_start, transaction_id, login_name = row
        parameters = {
            "backend_pid": int(backend_pid),
            "backend_start": backend_start,
            "transaction_id": str(transaction_id),
            "login_name": str(login_name),
            "subject": identity.subject,
            "clearance": int(identity.clearance),
            "corpora": ",".join(sorted(identity.corpora)),
            "classifications": ",".join(allowed_classifications(identity.clearance)),
            "compartments": ",".join(sorted(identity.compartments)),
            "roles": ",".join(sorted(identity.roles)),
        }
        with self.engine.begin() as broker:
            broker.execute(
                text(
                    "SELECT public.korpus_bind_rls_identity("
                    ":backend_pid, :backend_start, :transaction_id, :login_name, "
                    ":subject, :clearance, :corpora, :classifications, :compartments, :roles)"
                ),
                parameters,
            )

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
