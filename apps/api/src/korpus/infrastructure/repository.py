from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable
from contextlib import nullcontext, suppress
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import (
    create_engine,
    event,
    func,
    insert,
    inspect,
    select,
    update,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import DatabaseError, OperationalError
from sqlalchemy.pool import NullPool

from korpus.application.keyring import AuditKeyRing
from korpus.application.policy import PolicyEngine
from korpus.application.trace import current_trace_id
from korpus.domain.models import (
    AccessTier,
    AuditVerification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    ReviewState,
)
from korpus.infrastructure import retrieval_queries, row_mapping, review_transitions
from korpus.infrastructure.audit_anchor import AnchorError, AuditAnchorStore, FileAuditAnchorStore
from korpus.infrastructure.audit_reader import AuditReader, audit_canonical
from korpus.infrastructure.ingestion_schema import ingestion_jobs
from korpus.infrastructure.schema import (
    SCHEMA_REVISION,
    audit_anchor_outbox,
    audit_heads,
    audits,
    document_compartments,
    documents,
    metadata,
    span_embeddings,
    spans,
    versions,
)
from korpus.infrastructure.tenancy_schema import (
    accounts,
    billing_events,
    conversations,
    messages,
    plans,
    subscriptions,
)

__all__ = [
    "SCHEMA_REVISION",
    "ConcurrentWriteError",
    "SqlRepository",
    "accounts",
    "audit_anchor_outbox",
    "audit_heads",
    "audits",
    "billing_events",
    "conversations",
    "document_compartments",
    "documents",
    "messages",
    "metadata",
    "plans",
    "span_embeddings",
    "spans",
    "subscriptions",
    "versions",
]


class ConcurrentWriteError(RuntimeError):
    pass


T = TypeVar("T")


class SqlRepository:
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
    ) -> None:
        engine_options: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        if database_url.startswith("sqlite"):
            engine_options["connect_args"] = {
                "check_same_thread": False,
                "timeout": max(1, connect_timeout_seconds),
            }
            engine_options["poolclass"] = NullPool
        elif database_url.startswith("postgresql"):
            engine_options.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout_seconds,
                pool_recycle=pool_recycle_seconds,
                connect_args={
                    "connect_timeout": connect_timeout_seconds,
                    "options": (
                        f"-c statement_timeout={statement_timeout_ms} "
                        f"-c lock_timeout={lock_timeout_ms}"
                    ),
                },
            )
        self.engine = create_engine(database_url, **engine_options)
        review_url = review_database_url or os.getenv("KORPUS_REVIEW_DATABASE_URL") or database_url
        if review_url != database_url:
            primary, review = make_url(database_url), make_url(review_url)
            primary_target = (primary.get_backend_name(), primary.host, primary.port, primary.database)
            review_target = (review.get_backend_name(), review.host, review.port, review.database)
            if primary_target != review_target or primary.get_backend_name() != "postgresql":
                raise ValueError("review database identity must target the primary PostgreSQL database")
        self.review_engine = self.engine if review_url == database_url else create_engine(review_url, **engine_options)
        if database_url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._configure_sqlite)
        self.audit_key = audit_hmac_key.encode("utf-8")
        self.audit_keyring = audit_keyring or AuditKeyRing.single(self.audit_key)
        self.policy = policy or PolicyEngine()
        anchor_path = audit_anchor_path or Path("./var/audit-anchor.json")
        self.anchor_store: AuditAnchorStore = audit_anchor_store or FileAuditAnchorStore(
            anchor_path, self.audit_key
        )
        self._sqlite_write_lock = threading.RLock()
        self._anchor_delivery_lock = threading.Lock()
        self._audit_reader = AuditReader(
            self.engine,
            self.audit_key,
            self.audit_keyring,
            self.anchor_store,
            self._apply_postgres_identity,
            audits,
            audit_heads,
            audit_anchor_outbox,
            self.schema_revision,
            SCHEMA_REVISION,
        )

    @staticmethod
    def _configure_sqlite(dbapi_connection: Any, connection_record: Any) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    def initialize(self, *, create_schema: bool = True) -> None:
        if create_schema:
            metadata.create_all(self.engine)
            with self.engine.begin() as connection:
                self._initialize_search_index(connection)
        else:
            actual = set(inspect(self.engine).get_table_names())
            missing = set(metadata.tables).difference(actual)
            if missing:
                raise RuntimeError(f"database schema is not migrated: missing {sorted(missing)}")
            revision = self.schema_revision()
            if revision != SCHEMA_REVISION:
                raise RuntimeError(
                    f"database schema revision mismatch: expected {SCHEMA_REVISION}, "
                    f"got {revision or 'none'}"
                )
        with self.engine.begin() as connection:
            head = connection.execute(
                select(audit_heads.c.singleton_id).where(audit_heads.c.singleton_id == 1)
            ).scalar_one_or_none()
            if head is None:
                if not create_schema:
                    raise RuntimeError("migrated schema has no audit head")
                connection.execute(
                    insert(audit_heads).values(singleton_id=1, sequence=0, head_hash="0" * 64)
                )
        if not self.anchor_store.initialized():
            with self.engine.connect() as connection:
                sequence, head_hash = connection.execute(
                    select(audit_heads.c.sequence, audit_heads.c.head_hash).where(
                        audit_heads.c.singleton_id == 1
                    )
                ).one()
            if sequence == 0:
                self.anchor_store.write(0, head_hash)
        with suppress(AnchorError):
            self.reconcile_audit_anchor()

    def reset(self) -> None:
        if self.engine.dialect.name == "sqlite":
            with self.engine.begin() as connection:
                connection.execute(sql_text("DROP TABLE IF EXISTS evidence_fts"))
        metadata.drop_all(self.engine)
        self.anchor_store.reset()
        self.initialize()

    def create_document_bundle(
        self,
        actor: Identity,
        document: DocumentRecord,
        version: DocumentVersionRecord,
        records: list[EvidenceSpanRecord],
        audit_payload: dict[str, Any],
    ) -> None:
        def operation(connection: Connection) -> tuple[None, tuple[int, str]]:
            self._apply_postgres_identity(connection, actor)
            connection.execute(insert(documents).values(**self._document_values(document)))
            if document.compartments:
                connection.execute(
                    insert(document_compartments),
                    [
                        {"document_id": str(document.id), "compartment": value}
                        for value in sorted(document.compartments)
                    ],
                )
            connection.execute(insert(versions).values(**self._version_values(version)))
            if records:
                connection.execute(insert(spans), [self._span_values(record) for record in records])
                self._index_spans(connection, records)
            anchor = self._append_audit_in_connection(
                connection,
                actor,
                "document.ingested",
                "document_version",
                str(version.id),
                audit_payload,
            )
            return None, anchor

        self._transaction_with_anchor(operation)

    def create_version_bundle(
        self,
        actor: Identity,
        version: DocumentVersionRecord,
        records: list[EvidenceSpanRecord],
        audit_payload: dict[str, Any],
    ) -> None:
        def operation(connection: Connection) -> tuple[None, tuple[int, str]]:
            self._apply_postgres_identity(connection, actor)
            connection.execute(insert(versions).values(**self._version_values(version)))
            if records:
                connection.execute(insert(spans), [self._span_values(record) for record in records])
                self._index_spans(connection, records)
            anchor = self._append_audit_in_connection(
                connection,
                actor,
                "document.ingested",
                "document_version",
                str(version.id),
                audit_payload,
            )
            return None, anchor

        self._transaction_with_anchor(operation)

    def get_document(self, identity: Identity, document_id: UUID) -> DocumentRecord | None:
        with self.engine.begin() as connection:
            self._apply_postgres_identity(connection, identity)
            row = connection.execute(
                select(documents).where(documents.c.id == str(document_id))
            ).mappings().first()
        return self._document(row) if row else None

    def list_documents(self, identity: Identity) -> list[DocumentRecord]:
        allowed_classifications = self._allowed_classifications(identity.clearance)
        statement = (
            select(documents)
            .where(documents.c.corpus_id.in_(sorted(identity.corpora)))
            .where(documents.c.access_tier <= int(identity.clearance))
            .where(documents.c.classification.in_(allowed_classifications))
            .where(retrieval_queries.compartment_predicate(identity))
            .order_by(documents.c.created_at.desc(), documents.c.id)
        )
        with self.engine.begin() as connection:
            self._apply_postgres_identity(connection, identity)
            rows = connection.execute(statement).mappings().all()
        return [self._document(row) for row in rows]

    def get_version(self, identity: Identity, version_id: UUID) -> DocumentVersionRecord | None:
        statement = (
            select(versions)
            .join(documents, versions.c.document_id == documents.c.id)
            .where(versions.c.id == str(version_id))
        )
        with self.engine.begin() as connection:
            self._apply_postgres_identity(connection, identity)
            row = connection.execute(statement).mappings().first()
        return self._version(row) if row else None

    def find_near_duplicate(
        self,
        identity: Identity,
        content_fingerprint: str,
        *,
        corpus_id: str | None = None,
        document_id: UUID | None = None,
        minimum_similarity: float = 0.90,
    ) -> tuple[DocumentVersionRecord, float] | None:
        from korpus.application.fingerprints import simhash_similarity

        if not re.fullmatch(r"[a-f0-9]{16}", content_fingerprint):
            raise ValueError("invalid content fingerprint")
        if not 0.5 <= minimum_similarity <= 1.0:
            raise ValueError("invalid near-duplicate threshold")
        statement = (
            select(versions)
            .join(documents, versions.c.document_id == documents.c.id)
            .where(documents.c.corpus_id.in_(sorted(identity.corpora)))
            .where(documents.c.access_tier <= int(identity.clearance))
            .where(
                documents.c.classification.in_(
                    row_mapping.allowed_classifications(identity.clearance)
                )
            )
            .where(retrieval_queries.compartment_predicate(identity))
        )
        if corpus_id is not None:
            if corpus_id not in identity.corpora and not identity.has_role("admin"):
                return None
            statement = statement.where(documents.c.corpus_id == corpus_id)
        if document_id is not None:
            statement = statement.where(versions.c.document_id == str(document_id))
        with self.engine.begin() as connection:
            self._apply_postgres_identity(connection, identity)
            rows = connection.execute(statement.limit(50_000)).mappings().all()
        best: tuple[DocumentVersionRecord, float] | None = None
        for row in rows:
            candidate = self._version(row)
            similarity = simhash_similarity(content_fingerprint, candidate.content_fingerprint)
            if similarity >= minimum_similarity and (best is None or similarity > best[1]):
                best = (candidate, similarity)
        return best

    def find_version_by_hash(
        self,
        identity: Identity,
        source_hash: str,
        *,
        corpus_id: str | None = None,
        document_id: UUID | None = None,
        revision: str | None = None,
    ) -> DocumentVersionRecord | None:
        """Identical bytes under a different revision are a different version."""
        statement = select(versions)
        if revision is not None:
            statement = statement.where(versions.c.revision == revision)
        if document_id is not None:
            statement = statement.where(versions.c.document_id == str(document_id))
        elif corpus_id is not None:
            statement = statement.join(documents, versions.c.document_id == documents.c.id).where(
                documents.c.corpus_id == corpus_id
            )
        statement = statement.where(versions.c.source_hash == source_hash).limit(1)
        if document_id is not None:
            statement = statement.join(documents, versions.c.document_id == documents.c.id)
        with self.engine.begin() as connection:
            self._apply_postgres_identity(connection, identity)
            row = connection.execute(statement).mappings().first()
        return self._version(row) if row else None

    def transition_version(
        self,
        actor: Identity,
        version_id: UUID,
        expected_state: ReviewState,
        target_state: ReviewState,
        note: str,
        *,
        acknowledge_near_duplicate: bool = False,
        acknowledge_extraction_quality: bool = False,
        reviewer_credential_id: str | None = None,
        access_tier: AccessTier | None = None,
    ) -> DocumentVersionRecord:
        """Apply one optimistic review transition and append its audit event atomically."""

        def operation(connection: Connection) -> tuple[DocumentVersionRecord, tuple[int, str]]:
            self._apply_postgres_identity(connection, actor)
            try:
                return review_transitions.transition_version_in_connection(
                    connection,
                    actor=actor,
                    version_id=version_id,
                    expected_state=expected_state,
                    target_state=target_state,
                    note=note,
                    acknowledge_near_duplicate=acknowledge_near_duplicate,
                    acknowledge_extraction_quality=acknowledge_extraction_quality,
                    reviewer_credential_id=reviewer_credential_id,
                    access_tier=access_tier,
                    version_mapper=self._version,
                    document_mapper=self._document,
                    append_audit=self._append_audit_in_connection,
                )
            except review_transitions.ReviewTransitionConflict as exc:
                raise ConcurrentWriteError(str(exc)) from exc

        return self._transaction_with_anchor(operation, engine=self.review_engine)

    def rescind_version(
        self,
        actor: Identity,
        version_id: UUID,
        *,
        note: str,
        rescinded_at: datetime | None = None,
    ) -> DocumentVersionRecord:
        """Record that the issuing authority withdrew a document."""
        stamp = rescinded_at or datetime.now(UTC)

        def operation(connection: Connection) -> tuple[DocumentVersionRecord, tuple[int, str]]:
            self._apply_postgres_identity(connection, actor)
            row = connection.execute(
                select(versions).where(versions.c.id == str(version_id))
            ).mappings().first()
            if row is None:
                raise LookupError("version not found")
            current = self._version(row)
            if current.review_state is not ReviewState.APPROVED:
                raise ValueError("only an approved version can be rescinded")
            if current.rescinded_at is not None:
                raise ValueError("version is already rescinded")
            result = connection.execute(
                update(versions)
                .where(versions.c.id == str(version_id))
                .where(versions.c.state_version == current.state_version)
                .where(versions.c.rescinded_at.is_(None))
                .values(rescinded_at=stamp, state_version=current.state_version + 1)
            )
            if result.rowcount != 1:
                raise ConcurrentWriteError("optimistic rescission failed")
            updated = self._version(
                connection.execute(
                    select(versions).where(versions.c.id == str(version_id))
                ).mappings().one()
            )
            anchor = self._append_audit_in_connection(
                connection,
                actor,
                "document.rescinded",
                "document_version",
                str(version_id),
                {
                    "note": note,
                    "rescinded_at": self._iso(stamp),
                    "state_version": updated.state_version,
                },
            )
            return updated, anchor

        return self._transaction_with_anchor(operation)

    def list_retrievable_spans(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
        version_id: UUID | None = None,
    ) -> list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]]:
        authorized_corpora = corpus_ids.intersection(identity.corpora)
        if not authorized_corpora:
            return []
        statement = retrieval_queries.retrievable_projection(identity, authorized_corpora, as_of)
        if version_id is not None:
            statement = statement.where(versions.c.id == str(version_id))
        with self.engine.begin() as connection:
            self._apply_postgres_identity(connection, identity)
            rows = connection.execute(statement).mappings().all()
        return retrieval_queries.materialize_current(rows, as_of)

    def get_retrievable_spans_by_ids(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
        span_ids: list[UUID],
    ) -> list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]]:
        authorized_corpora = corpus_ids.intersection(identity.corpora)
        if not authorized_corpora or not span_ids:
            return []
        string_ids = [str(value) for value in span_ids]
        statement = retrieval_queries.retrievable_projection(
            identity, authorized_corpora, as_of
        ).where(spans.c.id.in_(string_ids))
        with self.engine.begin() as connection:
            self._apply_postgres_identity(connection, identity)
            rows = connection.execute(statement).mappings().all()
        by_id = {row["span_id"]: row for row in rows}
        ordered = [by_id[value] for value in string_ids if value in by_id]
        return retrieval_queries.materialize_current(ordered, as_of)

    def search_retrievable_spans(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
        query: str,
        candidate_limit: int,
    ) -> list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]]:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")
        authorized_corpora = corpus_ids.intersection(identity.corpora)
        if not authorized_corpora:
            return []
        with self.engine.begin() as connection:
            self._apply_postgres_identity(connection, identity)
            span_ids = self._candidate_span_ids(
                identity, authorized_corpora, as_of, query, candidate_limit * 4, connection
            )
            if not span_ids:
                return []
            statement = retrieval_queries.retrievable_projection(
                identity, authorized_corpora, as_of
            ).where(spans.c.id.in_(span_ids))
            rows = connection.execute(statement).mappings().all()
        by_id = {row["span_id"]: row for row in rows}
        ordered = [by_id[span_id] for span_id in span_ids if span_id in by_id]
        return retrieval_queries.materialize_current(ordered, as_of)[:candidate_limit]

    def _candidate_span_ids(
        self,
        identity: Identity,
        corpora: frozenset[str],
        as_of: date,
        query: str,
        limit: int,
        connection: Connection | None = None,
    ) -> list[str]:
        prepared = retrieval_queries.candidate_span_query(
            identity, corpora, as_of, query, limit, self.engine.dialect.name
        )
        if prepared is None:
            return []
        statement, parameters = prepared
        if connection is not None:
            return [row.span_id for row in connection.execute(statement, parameters)]
        with self.engine.begin() as owned_connection:
            self._apply_postgres_identity(owned_connection, identity)
            return [row.span_id for row in owned_connection.execute(statement, parameters)]

    @staticmethod
    def _apply_postgres_identity(connection: Connection, identity: Identity) -> None:
        del identity
        if connection.dialect.name == "postgresql":
            raise RuntimeError(
                "PostgreSQL identity binding requires RlsBoundSqlRepository"
            )

    def _initialize_search_index(self, connection: Connection) -> None:
        if self.engine.dialect.name == "sqlite":
            connection.execute(
                sql_text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts "
                    "USING fts5(span_id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2')"
                )
            )
        elif self.engine.dialect.name == "postgresql":
            connection.execute(
                sql_text(
                    "CREATE INDEX IF NOT EXISTS ix_evidence_spans_search "
                    "ON evidence_spans USING GIN (to_tsvector('simple', text))"
                )
            )

    def _index_spans(self, connection: Connection, records: list[EvidenceSpanRecord]) -> None:
        if self.engine.dialect.name != "sqlite" or not records:
            return
        connection.execute(
            sql_text("INSERT INTO evidence_fts(span_id, text) VALUES (:span_id, :text)"),
            [{"span_id": str(record.id), "text": record.text} for record in records],
        )

    def append_audit(
        self,
        actor: Identity,
        action: str,
        resource_type: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> str:
        def operation(connection: Connection) -> tuple[str, tuple[int, str]]:
            sequence, event_hash = self._append_audit_in_connection(
                connection, actor, action, resource_type, resource_id, payload
            )
            return event_hash, (sequence, event_hash)

        return self._transaction_with_anchor(operation)

    def reconcile_audit_anchor(self, *, limit: int | None = None) -> int:
        if not self._anchor_delivery_lock.acquire(blocking=False):
            return 0
        try:
            return self._reconcile_audit_anchor_locked(limit=limit)
        finally:
            self._anchor_delivery_lock.release()

    def _reconcile_audit_anchor_locked(self, *, limit: int | None = None) -> int:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(audit_anchor_outbox.c.sequence, audit_anchor_outbox.c.head_hash)
                .where(audit_anchor_outbox.c.delivered_at.is_(None))
                .order_by(audit_anchor_outbox.c.sequence.desc())
                .limit(1)
            ).one_or_none()
        if row is None:
            return 0
        self.anchor_store.write(row.sequence, row.head_hash)
        statement = (
            update(audit_anchor_outbox)
            .where(audit_anchor_outbox.c.delivered_at.is_(None))
            .where(audit_anchor_outbox.c.sequence <= row.sequence)
            .values(delivered_at=datetime.now(UTC))
        )
        if limit is not None:
            floor = (
                select(audit_anchor_outbox.c.sequence)
                .where(audit_anchor_outbox.c.delivered_at.is_(None))
                .where(audit_anchor_outbox.c.sequence <= row.sequence)
                .order_by(audit_anchor_outbox.c.sequence.desc())
                .limit(1)
                .offset(max(limit - 1, 0))
                .scalar_subquery()
            )
            statement = statement.where(
                audit_anchor_outbox.c.sequence >= func.coalesce(floor, 0)
            )
        with self.engine.begin() as connection:
            result = connection.execute(statement)
        return int(result.rowcount or 0)

    def read_audit_events(
        self, identity: Identity, trace_id: str, *, limit: int = 200
    ) -> list[dict[str, object]]:
        return self._audit_reader.read_audit_events(identity, trace_id, limit=limit)

    def verify_audit(self) -> AuditVerification:
        return self._audit_reader.verify_audit()

    def corpus_release_id(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
    ) -> str:
        authorized_corpora = corpus_ids.intersection(identity.corpora)
        if not authorized_corpora:
            unique_versions: set[tuple[str, str, str, str]] = set()
        else:
            statement = retrieval_queries.release_projection(identity, authorized_corpora, as_of)
            with self.engine.begin() as connection:
                self._apply_postgres_identity(connection, identity)
                rows = connection.execute(statement).mappings().all()
            unique_versions = {
                (
                    str(row["document_id"]),
                    str(row["version_id"]),
                    str(row["source_hash"]),
                    str(row["review_state"]),
                )
                for row in rows
                if retrieval_queries.release_row_is_current(row, as_of)
            }
        digest = hashlib.sha256()
        for row_key in sorted(unique_versions):
            digest.update(":".join(row_key).encode("utf-8") + b"\n")
        return digest.hexdigest()[:16]

    def schema_revision(self) -> str | None:
        try:
            with self.engine.connect() as connection:
                if "alembic_version" not in inspect(connection).get_table_names():
                    return None
                return connection.execute(
                    sql_text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
        except OperationalError:
            return None

    def object_inventory(self) -> dict[str, set[str]]:
        with self.engine.begin() as connection:
            content = {
                str(row.object_key)
                for row in connection.execute(select(versions.c.object_key)).all()
            }
            quarantine = {
                str(row.staging_object_key)
                for row in connection.execute(select(ingestion_jobs.c.staging_object_key)).all()
            }
        return {"content": content, "quarantine": quarantine}

    def healthcheck(self) -> bool:
        try:
            with self.engine.connect() as connection:
                probe: object = connection.execute(select(1)).scalar_one()
                if probe != 1:
                    return False
                return self._integrity_ok(connection)
        except (OperationalError, DatabaseError):
            return False

    def _integrity_ok(self, connection: Connection) -> bool:
        dialect = self.engine.dialect.name
        if dialect == "sqlite":
            rows = connection.execute(sql_text("PRAGMA quick_check(1)")).scalars().all()
            return [str(row).lower() for row in rows] == ["ok"]
        if dialect == "postgresql":
            row = connection.execute(
                sql_text(
                    "SELECT coalesce(sum(checksum_failures), 0) FROM pg_stat_database"
                    " WHERE datname = current_database()"
                )
            ).scalar_one()
            return int(row) == 0
        return True

    def readiness_snapshot(
        self, *, max_pending_events: int, max_pending_age_seconds: float
    ) -> dict[str, object]:
        return self._audit_reader.readiness_snapshot(
            max_pending_events=max_pending_events,
            max_pending_age_seconds=max_pending_age_seconds,
        )

    def close(self) -> None:
        try:
            self.anchor_store.close()
        finally:
            if self.review_engine is not self.engine:
                self.review_engine.dispose()
            self.engine.dispose()

    def audited_transaction(
        self,
        operation: Callable[[Connection], tuple[T, tuple[int, str]]],
    ) -> T:
        return self._transaction_with_anchor(operation)

    def audit_in_connection(
        self,
        connection: Connection,
        actor: Identity,
        action: str,
        resource_type: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> tuple[int, str]:
        return self._append_audit_in_connection(
            connection, actor, action, resource_type, resource_id, payload
        )

    def _transaction_with_anchor(
        self,
        operation: Callable[[Connection], tuple[T, tuple[int, str]]],
        retries: int = 8,
        *,
        engine: Any | None = None,
    ) -> T:
        last_error: Exception | None = None
        write_engine = engine or self.engine
        write_guard = (
            self._sqlite_write_lock if write_engine.dialect.name == "sqlite" else nullcontext()
        )
        with write_guard:
            for attempt in range(retries):
                try:
                    with write_engine.begin() as connection:
                        result, _anchor = operation(connection)
                    with suppress(AnchorError, OSError, TimeoutError):
                        self.reconcile_audit_anchor(limit=1)
                    return result
                except ConcurrentWriteError as exc:
                    last_error = exc
                except OperationalError as exc:
                    if "locked" not in str(exc).lower() and "serialization" not in str(exc).lower():
                        raise
                    last_error = exc
                time.sleep(0.002 * (2**attempt))
        raise ConcurrentWriteError("transaction retry budget exhausted") from last_error

    def _append_audit_in_connection(
        self,
        connection: Connection,
        actor: Identity,
        action: str,
        resource_type: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> tuple[int, str]:
        head_statement = select(audit_heads.c.sequence, audit_heads.c.head_hash).where(
            audit_heads.c.singleton_id == 1
        )
        if connection.dialect.name == "postgresql":
            head_statement = head_statement.with_for_update()
        head_sequence, previous_hash = connection.execute(head_statement).one()
        sequence = head_sequence + 1
        occurred_at = datetime.now(UTC)
        event_id = str(uuid4())
        trace_id = current_trace_id()
        stamped = payload if trace_id is None else {**payload, "trace_id": trace_id}
        payload_json = json.dumps(
            stamped, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        canonical = self._audit_canonical(
            sequence=sequence,
            event_id=event_id,
            occurred_at=occurred_at.isoformat(),
            actor_subject=actor.subject,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload_json=payload_json,
            previous_hash=previous_hash,
        )
        audit_key_id, event_hash = self.audit_keyring.sign(canonical)
        head_result = connection.execute(
            update(audit_heads)
            .where(audit_heads.c.singleton_id == 1)
            .where(audit_heads.c.sequence == head_sequence)
            .where(audit_heads.c.head_hash == previous_hash)
            .values(sequence=sequence, head_hash=event_hash)
        )
        if head_result.rowcount != 1:
            raise ConcurrentWriteError("audit head changed concurrently")
        connection.execute(
            insert(audits).values(
                sequence=sequence,
                event_id=event_id,
                event_schema_version=1,
                occurred_at=occurred_at,
                actor_subject=actor.subject,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                payload_json=payload_json,
                previous_hash=previous_hash,
                event_hash=event_hash,
                audit_key_id=audit_key_id,
            )
        )
        connection.execute(
            insert(audit_anchor_outbox).values(
                sequence=sequence,
                head_hash=event_hash,
                created_at=occurred_at,
                delivered_at=None,
            )
        )
        return sequence, event_hash

    _audit_canonical = staticmethod(audit_canonical)
    _retrievable_projection = staticmethod(retrieval_queries.retrievable_projection)
    _materialize_current = staticmethod(retrieval_queries.materialize_current)
    _compartment_predicate = staticmethod(retrieval_queries.compartment_predicate)
    _allowed_classifications = staticmethod(row_mapping.allowed_classifications)
    _iso = staticmethod(row_mapping.iso)
    _document_values = staticmethod(row_mapping.document_values)
    _version_values = staticmethod(row_mapping.version_values)
    _span_values = staticmethod(row_mapping.span_values)
    _document = staticmethod(row_mapping.document)
    _version = staticmethod(row_mapping.version)
    _document_from_projection = staticmethod(row_mapping.document_from_projection)
    _version_from_projection = staticmethod(row_mapping.version_from_projection)
    _span_from_projection = staticmethod(row_mapping.span_from_projection)
