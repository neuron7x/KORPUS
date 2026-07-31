from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Date,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

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

metadata = MetaData()

documents = Table(
    "documents",
    metadata,
    __import__("sqlalchemy").Column("id", String(36), primary_key=True),
    __import__("sqlalchemy").Column("canonical_title", String(500), nullable=False),
    __import__("sqlalchemy").Column("corpus_id", String(64), nullable=False, index=True),
    __import__("sqlalchemy").Column("issuer", String(300), nullable=False),
    __import__("sqlalchemy").Column("jurisdiction", String(50), nullable=False),
    __import__("sqlalchemy").Column("document_type", String(100), nullable=False),
    __import__("sqlalchemy").Column("access_tier", Integer, nullable=False),
    __import__("sqlalchemy").Column("classification", String(32), nullable=False),
    __import__("sqlalchemy").Column("created_at", DateTime(timezone=True), nullable=False),
)

versions = Table(
    "document_versions",
    metadata,
    __import__("sqlalchemy").Column("id", String(36), primary_key=True),
    __import__("sqlalchemy").Column("document_id", String(36), nullable=False, index=True),
    __import__("sqlalchemy").Column("revision", String(120), nullable=False),
    __import__("sqlalchemy").Column("publication_identifier", String(200)),
    __import__("sqlalchemy").Column("source_uri", Text),
    __import__("sqlalchemy").Column("source_hash", String(64), nullable=False, unique=True, index=True),
    __import__("sqlalchemy").Column("object_key", Text, nullable=False),
    __import__("sqlalchemy").Column("mime_type", String(200), nullable=False),
    __import__("sqlalchemy").Column("publication_date", Date),
    __import__("sqlalchemy").Column("effective_from", Date),
    __import__("sqlalchemy").Column("effective_until", Date),
    __import__("sqlalchemy").Column("rescinded_at", DateTime(timezone=True)),
    __import__("sqlalchemy").Column("authority", String(64), nullable=False),
    __import__("sqlalchemy").Column("review_state", String(64), nullable=False),
    __import__("sqlalchemy").Column("supersedes_version_id", String(36)),
    __import__("sqlalchemy").Column("created_at", DateTime(timezone=True), nullable=False),
)

spans = Table(
    "evidence_spans",
    metadata,
    __import__("sqlalchemy").Column("id", String(36), primary_key=True),
    __import__("sqlalchemy").Column("version_id", String(36), nullable=False, index=True),
    __import__("sqlalchemy").Column("ordinal", Integer, nullable=False),
    __import__("sqlalchemy").Column("page", Integer),
    __import__("sqlalchemy").Column("section", String(500)),
    __import__("sqlalchemy").Column("text", Text, nullable=False),
    __import__("sqlalchemy").Column("created_at", DateTime(timezone=True), nullable=False),
)

audits = Table(
    "audit_events",
    metadata,
    __import__("sqlalchemy").Column("sequence", Integer, primary_key=True, autoincrement=True),
    __import__("sqlalchemy").Column("event_id", String(36), nullable=False, unique=True),
    __import__("sqlalchemy").Column("occurred_at", DateTime(timezone=True), nullable=False),
    __import__("sqlalchemy").Column("actor_subject", String(200), nullable=False),
    __import__("sqlalchemy").Column("action", String(200), nullable=False),
    __import__("sqlalchemy").Column("resource_type", String(100), nullable=False),
    __import__("sqlalchemy").Column("resource_id", String(200)),
    __import__("sqlalchemy").Column("payload_json", Text, nullable=False),
    __import__("sqlalchemy").Column("previous_hash", String(64), nullable=False),
    __import__("sqlalchemy").Column("event_hash", String(64), nullable=False),
)


class SqlRepository:
    def __init__(self, database_url: str, audit_hmac_key: str, policy: PolicyEngine | None = None) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(database_url, future=True, connect_args=connect_args)
        self.audit_key = audit_hmac_key.encode("utf-8")
        self.policy = policy or PolicyEngine()

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def reset(self) -> None:
        metadata.drop_all(self.engine)
        metadata.create_all(self.engine)

    def create_document(self, document: DocumentRecord) -> DocumentRecord:
        with self.engine.begin() as connection:
            connection.execute(insert(documents).values(**self._document_values(document)))
        return document

    def create_document_bundle(
        self, document: DocumentRecord, version: DocumentVersionRecord, records: list[EvidenceSpanRecord]
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(insert(documents).values(**self._document_values(document)))
            connection.execute(insert(versions).values(**self._version_values(version)))
            if records:
                connection.execute(insert(spans), [self._span_values(record) for record in records])

    def create_version_bundle(
        self, version: DocumentVersionRecord, records: list[EvidenceSpanRecord]
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(insert(versions).values(**self._version_values(version)))
            if records:
                connection.execute(insert(spans), [self._span_values(record) for record in records])

    def get_document(self, document_id: UUID) -> DocumentRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(documents).where(documents.c.id == str(document_id))).mappings().first()
        return self._document(row) if row else None

    def list_documents(self, identity: Identity) -> list[DocumentRecord]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(documents).order_by(documents.c.created_at.desc())).mappings().all()
        records = [self._document(row) for row in rows]
        return [record for record in records if self.policy.can_access_document(identity, record).allowed]

    def create_version(self, version: DocumentVersionRecord) -> DocumentVersionRecord:
        with self.engine.begin() as connection:
            connection.execute(insert(versions).values(**self._version_values(version)))
        return version

    def get_version(self, version_id: UUID) -> DocumentVersionRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(versions).where(versions.c.id == str(version_id))).mappings().first()
        return self._version(row) if row else None

    def find_version_by_hash(self, source_hash: str) -> DocumentVersionRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(versions).where(versions.c.source_hash == source_hash)).mappings().first()
        return self._version(row) if row else None

    def update_version(self, version: DocumentVersionRecord) -> DocumentVersionRecord:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(versions).where(versions.c.id == str(version.id)).values(**self._version_values(version))
            )
            if result.rowcount != 1:
                raise LookupError("version not found")
        return version

    def add_spans(self, records: list[EvidenceSpanRecord]) -> None:
        if not records:
            return
        with self.engine.begin() as connection:
            connection.execute(insert(spans), [self._span_values(record) for record in records])

    def list_retrievable_spans(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
    ) -> list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]]:
        statement = (
            select(spans, documents, versions)
            .join(versions, spans.c.version_id == versions.c.id)
            .join(documents, versions.c.document_id == documents.c.id)
            .where(versions.c.review_state == ReviewState.APPROVED.value)
            .where(documents.c.corpus_id.in_(sorted(corpus_ids)))
            .order_by(documents.c.id, versions.c.created_at.desc(), spans.c.ordinal)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        authorized: list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]] = []
        for row in rows:
            document = self._document_from_join(row)
            version = self._version_from_join(row)
            span = self._span_from_join(row)
            if not self.policy.can_access_document(identity, document).allowed:
                continue
            if not version.is_active(as_of):
                continue
            authorized.append((span, document, version))
        superseded_ids = {
            version.supersedes_version_id
            for _, _, version in authorized
            if version.supersedes_version_id is not None
        }
        return [item for item in authorized if item[2].id not in superseded_ids]

    def append_audit(
        self,
        actor: Identity,
        action: str,
        resource_type: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> str:
        occurred_at = datetime.now(UTC)
        event_id = str(uuid4())
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.engine.begin() as connection:
            previous = connection.execute(select(audits.c.event_hash).order_by(audits.c.sequence.desc()).limit(1)).scalar_one_or_none()
            previous_hash = previous or "0" * 64
            canonical = json.dumps(
                {
                    "event_id": event_id,
                    "occurred_at": occurred_at.isoformat(),
                    "actor_subject": actor.subject,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "payload_json": payload_json,
                    "previous_hash": previous_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            event_hash = hmac.new(self.audit_key, canonical, hashlib.sha256).hexdigest()
            connection.execute(
                insert(audits).values(
                    event_id=event_id,
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
        return event_hash

    def verify_audit(self) -> AuditVerification:
        with self.engine.connect() as connection:
            rows = connection.execute(select(audits).order_by(audits.c.sequence)).mappings().all()
        previous_hash = "0" * 64
        for row in rows:
            canonical = json.dumps(
                {
                    "event_id": row["event_id"],
                    "occurred_at": self._iso(row["occurred_at"]),
                    "actor_subject": row["actor_subject"],
                    "action": row["action"],
                    "resource_type": row["resource_type"],
                    "resource_id": row["resource_id"],
                    "payload_json": row["payload_json"],
                    "previous_hash": row["previous_hash"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            expected = hmac.new(self.audit_key, canonical, hashlib.sha256).hexdigest()
            if row["previous_hash"] != previous_hash or not hmac.compare_digest(expected, row["event_hash"]):
                return AuditVerification(valid=False, event_count=len(rows), first_invalid_sequence=row["sequence"])
            previous_hash = row["event_hash"]
        return AuditVerification(valid=True, event_count=len(rows))

    def corpus_release_id(self) -> str:
        statement = select(versions.c.id, versions.c.source_hash, versions.c.review_state).order_by(versions.c.id)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).all()
        digest = hashlib.sha256()
        for version_id, source_hash, state in rows:
            digest.update(f"{version_id}:{source_hash}:{state}\n".encode())
        return digest.hexdigest()[:16]

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()

    @staticmethod
    def _document_values(record: DocumentRecord) -> dict[str, Any]:
        return {
            "id": str(record.id), "canonical_title": record.canonical_title, "corpus_id": record.corpus_id,
            "issuer": record.issuer, "jurisdiction": record.jurisdiction, "document_type": record.document_type,
            "access_tier": int(record.access_tier), "classification": record.classification.value,
            "created_at": record.created_at,
        }

    @staticmethod
    def _version_values(record: DocumentVersionRecord) -> dict[str, Any]:
        return {
            "id": str(record.id), "document_id": str(record.document_id), "revision": record.revision,
            "publication_identifier": record.publication_identifier, "source_uri": record.source_uri,
            "source_hash": record.source_hash, "object_key": record.object_key, "mime_type": record.mime_type,
            "publication_date": record.publication_date, "effective_from": record.effective_from,
            "effective_until": record.effective_until, "rescinded_at": record.rescinded_at,
            "authority": record.authority.value, "review_state": record.review_state.value,
            "supersedes_version_id": str(record.supersedes_version_id) if record.supersedes_version_id else None,
            "created_at": record.created_at,
        }

    @staticmethod
    def _span_values(record: EvidenceSpanRecord) -> dict[str, Any]:
        return {"id": str(record.id), "version_id": str(record.version_id), "ordinal": record.ordinal,
                "page": record.page, "section": record.section, "text": record.text, "created_at": record.created_at}

    @staticmethod
    def _document(row: Any) -> DocumentRecord:
        return DocumentRecord(id=UUID(row["id"]), canonical_title=row["canonical_title"], corpus_id=row["corpus_id"],
            issuer=row["issuer"], jurisdiction=row["jurisdiction"], document_type=row["document_type"],
            access_tier=AccessTier(row["access_tier"]), classification=Classification(row["classification"]),
            created_at=row["created_at"])

    def _version(self, row: Any) -> DocumentVersionRecord:
        return DocumentVersionRecord(id=UUID(row["id"]), document_id=UUID(row["document_id"]), revision=row["revision"],
            publication_identifier=row["publication_identifier"], source_uri=row["source_uri"], source_hash=row["source_hash"],
            object_key=row["object_key"], mime_type=row["mime_type"], publication_date=row["publication_date"],
            effective_from=row["effective_from"], effective_until=row["effective_until"], rescinded_at=row["rescinded_at"],
            authority=AuthorityClass(row["authority"]), review_state=ReviewState(row["review_state"]),
            supersedes_version_id=UUID(row["supersedes_version_id"]) if row["supersedes_version_id"] else None,
            created_at=row["created_at"])

    @staticmethod
    def _span(row: Any) -> EvidenceSpanRecord:
        return EvidenceSpanRecord(id=UUID(row["id"]), version_id=UUID(row["version_id"]), ordinal=row["ordinal"],
            page=row["page"], section=row["section"], text=row["text"], created_at=row["created_at"])

    def _document_from_join(self, row: Any) -> DocumentRecord:
        return DocumentRecord(id=UUID(row["id_1"]), canonical_title=row["canonical_title"], corpus_id=row["corpus_id"],
            issuer=row["issuer"], jurisdiction=row["jurisdiction"], document_type=row["document_type"],
            access_tier=AccessTier(row["access_tier"]), classification=Classification(row["classification"]),
            created_at=row["created_at_1"])

    def _version_from_join(self, row: Any) -> DocumentVersionRecord:
        return DocumentVersionRecord(id=UUID(row["id_2"]), document_id=UUID(row["document_id"]), revision=row["revision"],
            publication_identifier=row["publication_identifier"], source_uri=row["source_uri"], source_hash=row["source_hash"],
            object_key=row["object_key"], mime_type=row["mime_type"], publication_date=row["publication_date"],
            effective_from=row["effective_from"], effective_until=row["effective_until"], rescinded_at=row["rescinded_at"],
            authority=AuthorityClass(row["authority"]), review_state=ReviewState(row["review_state"]),
            supersedes_version_id=UUID(row["supersedes_version_id"]) if row["supersedes_version_id"] else None,
            created_at=row["created_at_2"])

    def _span_from_join(self, row: Any) -> EvidenceSpanRecord:
        return EvidenceSpanRecord(id=UUID(row["id"]), version_id=UUID(row["version_id"]), ordinal=row["ordinal"],
            page=row["page"], section=row["section"], text=row["text"], created_at=row["created_at"])
