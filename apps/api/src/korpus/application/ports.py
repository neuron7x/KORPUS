from __future__ import annotations

from datetime import date
from typing import Any, Protocol
from uuid import UUID

from korpus.domain.models import (
    AuditVerification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    RetrievedEvidence,
)


class Repository(Protocol):
    def initialize(self) -> None: ...

    def create_document(self, document: DocumentRecord) -> DocumentRecord: ...

    def create_document_bundle(
        self, document: DocumentRecord, version: DocumentVersionRecord, spans: list[EvidenceSpanRecord]
    ) -> None: ...

    def create_version_bundle(
        self, version: DocumentVersionRecord, spans: list[EvidenceSpanRecord]
    ) -> None: ...

    def get_document(self, document_id: UUID) -> DocumentRecord | None: ...

    def list_documents(self, identity: Identity) -> list[DocumentRecord]: ...

    def create_version(self, version: DocumentVersionRecord) -> DocumentVersionRecord: ...

    def get_version(self, version_id: UUID) -> DocumentVersionRecord | None: ...

    def find_version_by_hash(self, source_hash: str) -> DocumentVersionRecord | None: ...

    def update_version(self, version: DocumentVersionRecord) -> DocumentVersionRecord: ...

    def add_spans(self, spans: list[EvidenceSpanRecord]) -> None: ...

    def list_retrievable_spans(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
    ) -> list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]]: ...

    def append_audit(
        self,
        actor: Identity,
        action: str,
        resource_type: str,
        resource_id: str | None,
        payload: dict[str, Any],
    ) -> str: ...

    def verify_audit(self) -> AuditVerification: ...

    def corpus_release_id(self) -> str: ...


class ObjectStore(Protocol):
    def put(self, content: bytes, source_hash: str, filename: str) -> str: ...

    def get(self, object_key: str) -> bytes: ...


class Retriever(Protocol):
    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int = 8,
    ) -> list[RetrievedEvidence]: ...
