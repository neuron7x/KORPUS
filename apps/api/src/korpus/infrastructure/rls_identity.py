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


class RlsIdentityBinder:
    """Bind one application transaction to claims supplied through a separate DB login.

    The protected connection never writes authorization claims. It exposes only its
    server-assigned backend pid and transaction id; the broker login records the claims
    in a table the application/review logins cannot mutate. RLS policies resolve claims
    from those server-assigned identifiers, so arbitrary SQL on the protected login can
    no longer increase clearance/roles/corpora/classifications/compartments with SET.
    """

    def __init__(
        self,
        primary_database_url: str,
        identity_database_url: str | None,
        engine_options: dict[str, Any],
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
        primary, identity = make_url(primary_database_url), make_url(identity_database_url)
        if not identity.username or identity.username == primary.username:
            raise ValueError("RLS identity login must be distinct from the application login")
        self.engine = create_engine(identity_database_url, **engine_options)

    def bind(self, connection: Connection, identity: Identity) -> None:
        if connection.dialect.name != "postgresql":
            return
        if self.engine is None:
            raise RlsIdentityBindingError("PostgreSQL RLS identity broker is unavailable")
        backend_pid, transaction_id = connection.execute(
            text("SELECT pg_backend_pid(), pg_current_xact_id()::text")
        ).one()
        parameters = {
            "backend_pid": int(backend_pid),
            "transaction_id": str(transaction_id),
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
                    ":backend_pid, :transaction_id, :subject, :clearance, :corpora, "
                    ":classifications, :compartments, :roles)"
                ),
                parameters,
            )

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
