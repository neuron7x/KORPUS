from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Callable, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    insert,
    inspect,
    select,
    update,
    text as sql_text,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError

from korpus.application.policy import PolicyEngine
from korpus.domain.models import (
    AccessTier,
    AuditVerification,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    ReviewState,
)
from korpus.infrastructure.audit_anchor import AnchorError, FileAuditAnchorStore

metadata = MetaData()

documents = Table(
    "documents",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("canonical_title", String(500), nullable=False),
    Column("corpus_id", String(64), nullable=False, index=True),
    Column("issuer", String(300), nullable=False),
    Column("jurisdiction", String(50), nullable=False),
    Column("document_type", String(100), nullable=False),
    Column("access_tier", Integer, nullable=False),
    Column("classification", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("access_tier >= 0 AND access_tier <= 3", name="ck_document_access_tier"),
)

versions = Table(
    "document_versions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("document_id", String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("revision", String(120), nullable=False),
    Column("publication_identifier", String(200)),
    Column("source_uri", Text),
    Column("source_hash", String(64), nullable=False, index=True),
    Column("object_key", Text, nullable=False),
    Column("mime_type", String(200), nullable=False),
    Column("publication_date", Date),
    Column("effective_from", Date),
    Column("effective_until", Date),
    Column("rescinded_at", DateTime(timezone=True)),
    Column("authority", String(64), nullable=False),
    Column("review_state", String(64), nullable=False),
    Column("supersedes_version_id", String(36), ForeignKey("document_versions.id")),
    Column("state_version", Integer, nullable=False, default=0),
    Column("metadata_reviewed_by", String(200)),
    Column("content_reviewed_by", String(200)),
    Column("approved_at", DateTime(timezone=True)),
    Column("approved_by", String(200)),
    Column("is_current", Boolean, nullable=False, default=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("document_id", "source_hash", name="uq_version_document_source_hash"),
    CheckConstraint("state_version >= 0", name="ck_version_state_version"),
)

spans = Table(
    "evidence_spans",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("version_id", String(36), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("ordinal", Integer, nullable=False),
    Column("page", Integer),
    Column("section", String(500)),
    Column("text", Text, nullable=False),
    Column("text_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("version_id", "ordinal", name="uq_span_version_ordinal"),
)

audits = Table(
    "audit_events",
    metadata,
    Column("sequence", Integer, primary_key=True),
    Column("event_id", String(36), nullable=False, unique=True),
    Column("event_schema_version", Integer, nullable=False, default=1),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("actor_subject", String(200), nullable=False),
    Column("action", String(200), nullable=False),
    Column("resource_type", String(100), nullable=False),
    Column("resource_id", String(200)),
    Column("payload_json", Text, nullable=False),
    Column("previous_hash", String(64), nullable=False),
    Column("event_hash", String(64), nullable=False),
)

audit_anchor_outbox = Table(
    "audit_anchor_outbox",
    metadata,
    Column(
        "sequence",
        Integer,
        ForeignKey("audit_events.sequence", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("head_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("delivered_at", DateTime(timezone=True)),
)

audit_heads = Table(
    "audit_heads",
    metadata,
    Column("singleton_id", Integer, primary_key=True),
    Column("sequence", Integer, nullable=False),
    Column("head_hash", String(64), nullable=False),
    CheckConstraint("singleton_id = 1", name="ck_audit_head_singleton"),
)


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
    ) -> None:
        connect_args = {"check_same_thread": False, "timeout": 30} if database_url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(database_url, future=True, connect_args=connect_args, pool_pre_ping=True)
        if database_url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._configure_sqlite)
        self.audit_key = audit_hmac_key.encode("utf-8")
        self.policy = policy or PolicyEngine()
        anchor_path = audit_anchor_path or Path("./var/audit-anchor.json")
        self.anchor_store = FileAuditAnchorStore(anchor_path, self.audit_key)

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
        if not self.anchor_store.path.exists():
            with self.engine.connect() as connection:
                sequence, head_hash = connection.execute(
                    select(audit_heads.c.sequence, audit_heads.c.head_hash).where(audit_heads.c.singleton_id == 1)
                ).one()
            if sequence == 0:
                self.anchor_store.write(0, head_hash)
        self.reconcile_audit_anchor()

    def reset(self) -> None:
        if self.engine.dialect.name == "sqlite":
            with self.engine.begin() as connection:
                connection.execute(sql_text("DROP TABLE IF EXISTS evidence_fts"))
        metadata.drop_all(self.engine)
        if self.anchor_store.path.exists():
            self.anchor_store.path.unlink()
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
            connection.execute(insert(documents).values(**self._document_values(document)))
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

    def get_document(self, document_id: UUID) -> DocumentRecord | None:
        with self.engine.connect() as connection:
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
            .order_by(documents.c.created_at.desc(), documents.c.id)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._document(row) for row in rows]

    def get_version(self, version_id: UUID) -> DocumentVersionRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(versions).where(versions.c.id == str(version_id))
            ).mappings().first()
        return self._version(row) if row else None

    def find_version_by_hash(
        self,
        source_hash: str,
        *,
        corpus_id: str | None = None,
        document_id: UUID | None = None,
    ) -> DocumentVersionRecord | None:
        statement = select(versions)
        if document_id is not None:
            statement = statement.where(versions.c.document_id == str(document_id))
        elif corpus_id is not None:
            statement = statement.join(documents, versions.c.document_id == documents.c.id).where(
                documents.c.corpus_id == corpus_id
            )
        statement = statement.where(versions.c.source_hash == source_hash).limit(1)
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return self._version(row) if row else None

    def transition_version(
        self,
        actor: Identity,
        version_id: UUID,
        expected_state: ReviewState,
        target_state: ReviewState,
        note: str,
    ) -> DocumentVersionRecord:
        def operation(connection: Connection) -> tuple[DocumentVersionRecord, tuple[int, str]]:
            row = connection.execute(
                select(versions).where(versions.c.id == str(version_id))
            ).mappings().first()
            if row is None:
                raise LookupError("version not found")
            current = self._version(row)
            if current.review_state is not expected_state:
                raise ConcurrentWriteError("version state changed concurrently")

            changes: dict[str, Any] = {
                "review_state": target_state.value,
                "state_version": current.state_version + 1,
            }
            if target_state is ReviewState.METADATA_REVIEWED:
                changes["metadata_reviewed_by"] = actor.subject
            elif target_state is ReviewState.CONTENT_REVIEWED:
                changes["content_reviewed_by"] = actor.subject
            elif target_state is ReviewState.APPROVED:
                existing_row = connection.execute(
                    select(versions)
                    .where(versions.c.document_id == str(current.document_id))
                    .where(versions.c.review_state == ReviewState.APPROVED.value)
                    .where(versions.c.is_current.is_(True))
                    .where(versions.c.id != str(current.id))
                ).mappings().first()
                if existing_row is not None:
                    existing = self._version(existing_row)
                    if current.supersedes_version_id != existing.id:
                        raise ValueError("approval must supersede the current approved version")
                    connection.execute(
                        update(versions)
                        .where(versions.c.id == str(existing.id))
                        .where(versions.c.is_current.is_(True))
                        .values(is_current=False, state_version=existing.state_version + 1)
                    )
                elif current.supersedes_version_id is not None:
                    predecessor_row = connection.execute(
                        select(versions).where(versions.c.id == str(current.supersedes_version_id))
                    ).mappings().first()
                    if predecessor_row is None or predecessor_row["review_state"] != ReviewState.APPROVED.value:
                        raise ValueError("superseded version must be approved")
                changes.update(
                    {
                        "approved_at": datetime.now(UTC),
                        "approved_by": actor.subject,
                        "is_current": True,
                    }
                )
            elif target_state is ReviewState.REJECTED:
                changes["is_current"] = False

            result = connection.execute(
                update(versions)
                .where(versions.c.id == str(version_id))
                .where(versions.c.review_state == expected_state.value)
                .where(versions.c.state_version == current.state_version)
                .values(**changes)
            )
            if result.rowcount != 1:
                raise ConcurrentWriteError("optimistic review transition failed")
            updated_row = connection.execute(
                select(versions).where(versions.c.id == str(version_id))
            ).mappings().one()
            updated = self._version(updated_row)
            anchor = self._append_audit_in_connection(
                connection,
                actor,
                "document.review_transition",
                "document_version",
                str(version_id),
                {
                    "from": expected_state.value,
                    "to": target_state.value,
                    "note": note,
                    "state_version": updated.state_version,
                    "approved_by": updated.approved_by,
                },
            )
            return updated, anchor

        return self._transaction_with_anchor(operation)

    def list_retrievable_spans(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
    ) -> list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]]:
        authorized_corpora = corpus_ids.intersection(identity.corpora)
        if not authorized_corpora:
            return []
        statement = self._retrievable_projection(identity, authorized_corpora, as_of)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return self._materialize_current(rows, as_of)

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
        span_ids = self._candidate_span_ids(
            identity, authorized_corpora, as_of, query, candidate_limit * 4
        )
        if not span_ids:
            return []
        statement = self._retrievable_projection(identity, authorized_corpora, as_of).where(
            spans.c.id.in_(span_ids)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        by_id = {row["span_id"]: row for row in rows}
        ordered = [by_id[span_id] for span_id in span_ids if span_id in by_id]
        return self._materialize_current(ordered, as_of)[:candidate_limit]

    def _retrievable_projection(
        self, identity: Identity, authorized_corpora: frozenset[str], as_of: date
    ) -> Any:
        allowed_classifications = self._allowed_classifications(identity.clearance)
        superseding = versions.alias("superseding_version")
        active_superseder = (
            select(1)
            .where(superseding.c.supersedes_version_id == versions.c.id)
            .where(superseding.c.review_state == ReviewState.APPROVED.value)
            .where(
                (superseding.c.effective_from.is_(None))
                | (superseding.c.effective_from <= as_of)
            )
            .where(
                (superseding.c.effective_until.is_(None))
                | (superseding.c.effective_until >= as_of)
            )
            .where(
                (superseding.c.rescinded_at.is_(None))
                | (func.date(superseding.c.rescinded_at) > as_of)
            )
            .exists()
        )
        return (
            select(
                spans.c.id.label("span_id"),
                spans.c.version_id.label("span_version_id"),
                spans.c.ordinal,
                spans.c.page,
                spans.c.section,
                spans.c.text,
                spans.c.text_hash,
                spans.c.created_at.label("span_created_at"),
                documents.c.id.label("document_id"),
                documents.c.canonical_title,
                documents.c.corpus_id,
                documents.c.issuer,
                documents.c.jurisdiction,
                documents.c.document_type,
                documents.c.access_tier,
                documents.c.classification,
                documents.c.created_at.label("document_created_at"),
                versions.c.id.label("version_id"),
                versions.c.revision,
                versions.c.publication_identifier,
                versions.c.source_uri,
                versions.c.source_hash,
                versions.c.object_key,
                versions.c.mime_type,
                versions.c.publication_date,
                versions.c.effective_from,
                versions.c.effective_until,
                versions.c.rescinded_at,
                versions.c.authority,
                versions.c.review_state,
                versions.c.supersedes_version_id,
                versions.c.state_version,
                versions.c.metadata_reviewed_by,
                versions.c.content_reviewed_by,
                versions.c.approved_at,
                versions.c.approved_by,
                versions.c.is_current,
                versions.c.created_at.label("version_created_at"),
            )
            .join(versions, spans.c.version_id == versions.c.id)
            .join(documents, versions.c.document_id == documents.c.id)
            .where(versions.c.review_state == ReviewState.APPROVED.value)
            .where(documents.c.corpus_id.in_(sorted(authorized_corpora)))
            .where(documents.c.access_tier <= int(identity.clearance))
            .where(documents.c.classification.in_(allowed_classifications))
            .where(~active_superseder)
            .order_by(documents.c.id, versions.c.created_at.desc(), spans.c.ordinal)
        )

    def _materialize_current(
        self, rows: list[Any], as_of: date
    ) -> list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]]:
        authorized: list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]] = []
        for row in rows:
            version = self._version_from_projection(row)
            if not version.is_valid_on(as_of):
                continue
            authorized.append(
                (self._span_from_projection(row), self._document_from_projection(row), version)
            )
        return authorized

    def _candidate_span_ids(
        self,
        identity: Identity,
        corpora: frozenset[str],
        as_of: date,
        query: str,
        limit: int,
    ) -> list[str]:
        from korpus.application.retrieval import tokenize

        terms = tokenize(query)
        if not terms:
            return []
        classifications = self._allowed_classifications(identity.clearance)
        corpus_placeholders = ",".join(f":corpus_{index}" for index, _ in enumerate(sorted(corpora)))
        class_placeholders = ",".join(
            f":class_{index}" for index, _ in enumerate(classifications)
        )
        parameters: dict[str, Any] = {
            "clearance": int(identity.clearance),
            "as_of": as_of.isoformat(),
            "limit": limit,
        }
        parameters.update({f"corpus_{index}": value for index, value in enumerate(sorted(corpora))})
        parameters.update(
            {f"class_{index}": value for index, value in enumerate(classifications)}
        )
        if self.engine.dialect.name == "sqlite":
            match_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
            parameters["query"] = match_query
            statement = sql_text(
                f"""
                SELECT s.id AS span_id
                FROM evidence_fts f
                JOIN evidence_spans s ON s.id = f.span_id
                JOIN document_versions v ON v.id = s.version_id
                JOIN documents d ON d.id = v.document_id
                WHERE evidence_fts MATCH :query
                  AND v.review_state = 'approved'
                  AND d.corpus_id IN ({corpus_placeholders})
                  AND d.access_tier <= :clearance
                  AND d.classification IN ({class_placeholders})
                  AND (v.effective_from IS NULL OR v.effective_from <= :as_of)
                  AND (v.effective_until IS NULL OR v.effective_until >= :as_of)
                  AND (v.rescinded_at IS NULL OR date(v.rescinded_at) > :as_of)
                  AND NOT EXISTS (
                    SELECT 1 FROM document_versions sv
                    WHERE sv.supersedes_version_id = v.id
                      AND sv.review_state = 'approved'
                      AND (sv.effective_from IS NULL OR sv.effective_from <= :as_of)
                      AND (sv.effective_until IS NULL OR sv.effective_until >= :as_of)
                      AND (sv.rescinded_at IS NULL OR date(sv.rescinded_at) > :as_of)
                  )
                ORDER BY bm25(evidence_fts), s.id
                LIMIT :limit
                """
            )
        elif self.engine.dialect.name == "postgresql":
            parameters["query"] = " ".join(terms)
            statement = sql_text(
                f"""
                SELECT s.id AS span_id
                FROM evidence_spans s
                JOIN document_versions v ON v.id = s.version_id
                JOIN documents d ON d.id = v.document_id
                WHERE to_tsvector('simple', s.text) @@ plainto_tsquery('simple', :query)
                  AND v.review_state = 'approved'
                  AND d.corpus_id IN ({corpus_placeholders})
                  AND d.access_tier <= :clearance
                  AND d.classification IN ({class_placeholders})
                  AND (v.effective_from IS NULL OR v.effective_from <= CAST(:as_of AS date))
                  AND (v.effective_until IS NULL OR v.effective_until >= CAST(:as_of AS date))
                  AND (v.rescinded_at IS NULL OR CAST(v.rescinded_at AS date) > CAST(:as_of AS date))
                  AND NOT EXISTS (
                    SELECT 1 FROM document_versions sv
                    WHERE sv.supersedes_version_id = v.id
                      AND sv.review_state = 'approved'
                      AND (sv.effective_from IS NULL OR sv.effective_from <= CAST(:as_of AS date))
                      AND (sv.effective_until IS NULL OR sv.effective_until >= CAST(:as_of AS date))
                      AND (sv.rescinded_at IS NULL OR CAST(sv.rescinded_at AS date) > CAST(:as_of AS date))
                  )
                ORDER BY ts_rank_cd(
                    to_tsvector('simple', s.text), plainto_tsquery('simple', :query)
                ) DESC, s.id
                LIMIT :limit
                """
            )
        else:
            raise RuntimeError(f"unsupported search dialect: {self.engine.dialect.name}")
        with self.engine.connect() as connection:
            return [row.span_id for row in connection.execute(statement, parameters)]

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

    def reconcile_audit_anchor(self) -> int:
        """Deliver committed audit checkpoints to the external anchor.

        The database transaction records an outbox row atomically with every
        audit event. A crash between commit and file anchoring is therefore
        recoverable without replaying the business operation.
        """
        delivered = 0
        while True:
            with self.engine.connect() as connection:
                row = connection.execute(
                    select(
                        audit_anchor_outbox.c.sequence,
                        audit_anchor_outbox.c.head_hash,
                    )
                    .where(audit_anchor_outbox.c.delivered_at.is_(None))
                    .order_by(audit_anchor_outbox.c.sequence)
                    .limit(1)
                ).one_or_none()
            if row is None:
                return delivered
            self.anchor_store.write(row.sequence, row.head_hash)
            with self.engine.begin() as connection:
                result = connection.execute(
                    update(audit_anchor_outbox)
                    .where(audit_anchor_outbox.c.sequence == row.sequence)
                    .where(audit_anchor_outbox.c.delivered_at.is_(None))
                    .values(delivered_at=datetime.now(UTC))
                )
                delivered += int(result.rowcount == 1)

    def verify_audit(self) -> AuditVerification:
        with self.engine.connect() as connection:
            rows = connection.execute(select(audits).order_by(audits.c.sequence)).mappings().all()
            head_sequence, head_hash = connection.execute(
                select(audit_heads.c.sequence, audit_heads.c.head_hash).where(audit_heads.c.singleton_id == 1)
            ).one()
        previous_hash = "0" * 64
        expected_sequence = 1
        for row in rows:
            if row["sequence"] != expected_sequence:
                return AuditVerification(
                    valid=False,
                    event_count=len(rows),
                    head_sequence=head_sequence,
                    anchor_valid=False,
                    first_invalid_sequence=expected_sequence,
                    reason="audit sequence gap",
                )
            canonical = self._audit_canonical(
                sequence=row["sequence"],
                event_id=row["event_id"],
                occurred_at=self._iso(row["occurred_at"]),
                actor_subject=row["actor_subject"],
                action=row["action"],
                resource_type=row["resource_type"],
                resource_id=row["resource_id"],
                payload_json=row["payload_json"],
                previous_hash=row["previous_hash"],
            )
            expected_hash = hmac.new(self.audit_key, canonical, hashlib.sha256).hexdigest()
            if row["previous_hash"] != previous_hash or not hmac.compare_digest(expected_hash, row["event_hash"]):
                return AuditVerification(
                    valid=False,
                    event_count=len(rows),
                    head_sequence=head_sequence,
                    anchor_valid=False,
                    first_invalid_sequence=row["sequence"],
                    reason="audit hash mismatch",
                )
            previous_hash = row["event_hash"]
            expected_sequence += 1
        if head_sequence != len(rows) or head_hash != previous_hash:
            return AuditVerification(
                valid=False,
                event_count=len(rows),
                head_sequence=head_sequence,
                anchor_valid=False,
                reason="database audit head mismatch",
            )
        try:
            anchor = self.anchor_store.read()
        except AnchorError as exc:
            return AuditVerification(
                valid=False,
                event_count=len(rows),
                head_sequence=head_sequence,
                anchor_valid=False,
                reason=str(exc),
            )
        anchor_valid = anchor.sequence == head_sequence and anchor.head_hash == head_hash
        return AuditVerification(
            valid=anchor_valid,
            event_count=len(rows),
            head_sequence=head_sequence,
            anchor_valid=anchor_valid,
            reason=None if anchor_valid else "external audit anchor mismatch",
        )

    def corpus_release_id(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
    ) -> str:
        retrievable = self.list_retrievable_spans(identity, corpus_ids, as_of)
        unique_versions = {
            (str(document.id), str(version.id), version.source_hash, version.review_state.value)
            for _, document, version in retrievable
        }
        digest = hashlib.sha256()
        for row in sorted(unique_versions):
            digest.update(":".join(row).encode("utf-8") + b"\n")
        return digest.hexdigest()[:16]

    def healthcheck(self) -> bool:
        with self.engine.connect() as connection:
            return connection.execute(select(1)).scalar_one() == 1

    def _transaction_with_anchor(
        self,
        operation: Callable[[Connection], tuple[T, tuple[int, str]]],
        retries: int = 8,
    ) -> T:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                with self.engine.begin() as connection:
                    result, _anchor = operation(connection)
                self.reconcile_audit_anchor()
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
        head_sequence, previous_hash = connection.execute(
            select(audit_heads.c.sequence, audit_heads.c.head_hash).where(audit_heads.c.singleton_id == 1)
        ).one()
        sequence = head_sequence + 1
        occurred_at = datetime.now(UTC)
        event_id = str(uuid4())
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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
        event_hash = hmac.new(self.audit_key, canonical, hashlib.sha256).hexdigest()
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

    @staticmethod
    def _audit_canonical(
        *,
        sequence: int,
        event_id: str,
        occurred_at: str,
        actor_subject: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        payload_json: str,
        previous_hash: str,
    ) -> bytes:
        return json.dumps(
            {
                "schema": 1,
                "sequence": sequence,
                "event_id": event_id,
                "occurred_at": occurred_at,
                "actor_subject": actor_subject,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "payload_json": payload_json,
                "previous_hash": previous_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _allowed_classifications(clearance: AccessTier) -> list[str]:
        allowed = [Classification.PUBLIC.value]
        if clearance >= AccessTier.AUTHENTICATED:
            allowed.append(Classification.INTERNAL.value)
        if clearance >= AccessTier.RESTRICTED:
            allowed.append(Classification.RESTRICTED.value)
        return allowed

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()

    @staticmethod
    def _document_values(record: DocumentRecord) -> dict[str, Any]:
        return {
            "id": str(record.id),
            "canonical_title": record.canonical_title,
            "corpus_id": record.corpus_id,
            "issuer": record.issuer,
            "jurisdiction": record.jurisdiction,
            "document_type": record.document_type,
            "access_tier": int(record.access_tier),
            "classification": record.classification.value,
            "created_at": record.created_at,
        }

    @staticmethod
    def _version_values(record: DocumentVersionRecord) -> dict[str, Any]:
        return {
            "id": str(record.id),
            "document_id": str(record.document_id),
            "revision": record.revision,
            "publication_identifier": record.publication_identifier,
            "source_uri": record.source_uri,
            "source_hash": record.source_hash,
            "object_key": record.object_key,
            "mime_type": record.mime_type,
            "publication_date": record.publication_date,
            "effective_from": record.effective_from,
            "effective_until": record.effective_until,
            "rescinded_at": record.rescinded_at,
            "authority": record.authority.value,
            "review_state": record.review_state.value,
            "supersedes_version_id": str(record.supersedes_version_id) if record.supersedes_version_id else None,
            "state_version": record.state_version,
            "metadata_reviewed_by": record.metadata_reviewed_by,
            "content_reviewed_by": record.content_reviewed_by,
            "approved_at": record.approved_at,
            "approved_by": record.approved_by,
            "is_current": record.is_current,
            "created_at": record.created_at,
        }

    @staticmethod
    def _span_values(record: EvidenceSpanRecord) -> dict[str, Any]:
        return {
            "id": str(record.id),
            "version_id": str(record.version_id),
            "ordinal": record.ordinal,
            "page": record.page,
            "section": record.section,
            "text": record.text,
            "text_hash": record.text_hash,
            "created_at": record.created_at,
        }

    @staticmethod
    def _document(row: Any) -> DocumentRecord:
        return DocumentRecord(
            id=UUID(row["id"]),
            canonical_title=row["canonical_title"],
            corpus_id=row["corpus_id"],
            issuer=row["issuer"],
            jurisdiction=row["jurisdiction"],
            document_type=row["document_type"],
            access_tier=AccessTier(row["access_tier"]),
            classification=Classification(row["classification"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _version(row: Any) -> DocumentVersionRecord:
        return DocumentVersionRecord(
            id=UUID(row["id"]),
            document_id=UUID(row["document_id"]),
            revision=row["revision"],
            publication_identifier=row["publication_identifier"],
            source_uri=row["source_uri"],
            source_hash=row["source_hash"],
            object_key=row["object_key"],
            mime_type=row["mime_type"],
            publication_date=row["publication_date"],
            effective_from=row["effective_from"],
            effective_until=row["effective_until"],
            rescinded_at=row["rescinded_at"],
            authority=AuthorityClass(row["authority"]),
            review_state=ReviewState(row["review_state"]),
            supersedes_version_id=UUID(row["supersedes_version_id"]) if row["supersedes_version_id"] else None,
            state_version=row["state_version"],
            metadata_reviewed_by=row["metadata_reviewed_by"],
            content_reviewed_by=row["content_reviewed_by"],
            approved_at=row["approved_at"],
            approved_by=row["approved_by"],
            is_current=bool(row["is_current"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _document_from_projection(row: Any) -> DocumentRecord:
        return DocumentRecord(
            id=UUID(row["document_id"]),
            canonical_title=row["canonical_title"],
            corpus_id=row["corpus_id"],
            issuer=row["issuer"],
            jurisdiction=row["jurisdiction"],
            document_type=row["document_type"],
            access_tier=AccessTier(row["access_tier"]),
            classification=Classification(row["classification"]),
            created_at=row["document_created_at"],
        )

    @staticmethod
    def _version_from_projection(row: Any) -> DocumentVersionRecord:
        return DocumentVersionRecord(
            id=UUID(row["version_id"]),
            document_id=UUID(row["document_id"]),
            revision=row["revision"],
            publication_identifier=row["publication_identifier"],
            source_uri=row["source_uri"],
            source_hash=row["source_hash"],
            object_key=row["object_key"],
            mime_type=row["mime_type"],
            publication_date=row["publication_date"],
            effective_from=row["effective_from"],
            effective_until=row["effective_until"],
            rescinded_at=row["rescinded_at"],
            authority=AuthorityClass(row["authority"]),
            review_state=ReviewState(row["review_state"]),
            supersedes_version_id=UUID(row["supersedes_version_id"]) if row["supersedes_version_id"] else None,
            state_version=row["state_version"],
            metadata_reviewed_by=row["metadata_reviewed_by"],
            content_reviewed_by=row["content_reviewed_by"],
            approved_at=row["approved_at"],
            approved_by=row["approved_by"],
            is_current=bool(row["is_current"]),
            created_at=row["version_created_at"],
        )

    @staticmethod
    def _span_from_projection(row: Any) -> EvidenceSpanRecord:
        return EvidenceSpanRecord(
            id=UUID(row["span_id"]),
            version_id=UUID(row["span_version_id"]),
            ordinal=row["ordinal"],
            page=row["page"],
            section=row["section"],
            text=row["text"],
            text_hash=row["text_hash"],
            created_at=row["span_created_at"],
        )
