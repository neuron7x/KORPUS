from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from korpus.domain.models import (
    AuditVerification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    RetrievedEvidence,
    ReviewState,
)


class Repository(Protocol):
    def initialize(self) -> None: ...

    def create_document_bundle(
        self,
        actor: Identity,
        document: DocumentRecord,
        version: DocumentVersionRecord,
        spans: list[EvidenceSpanRecord],
        audit_payload: dict[str, Any],
    ) -> None: ...

    def create_version_bundle(
        self,
        actor: Identity,
        version: DocumentVersionRecord,
        spans: list[EvidenceSpanRecord],
        audit_payload: dict[str, Any],
    ) -> None: ...

    def get_document(self, identity: Identity, document_id: UUID) -> DocumentRecord | None: ...

    def list_documents(self, identity: Identity) -> list[DocumentRecord]: ...

    def get_version(self, identity: Identity, version_id: UUID) -> DocumentVersionRecord | None: ...

    def find_near_duplicate(
        self,
        identity: Identity,
        content_fingerprint: str,
        *,
        corpus_id: str | None = None,
        document_id: UUID | None = None,
        minimum_similarity: float = 0.90,
    ) -> tuple[DocumentVersionRecord, float] | None: ...

    def find_version_by_hash(
        self,
        identity: Identity,
        source_hash: str,
        *,
        corpus_id: str | None = None,
        document_id: UUID | None = None,
    ) -> DocumentVersionRecord | None: ...

    def transition_version(
        self,
        actor: Identity,
        version_id: UUID,
        expected_state: ReviewState,
        target_state: ReviewState,
        note: str,
        acknowledge_near_duplicate: bool = False,
        acknowledge_extraction_quality: bool = False,
        reviewer_credential_id: str | None = None,
    ) -> DocumentVersionRecord: ...

    def list_retrievable_spans(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
    ) -> list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]]: ...

    def get_retrievable_spans_by_ids(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
        span_ids: list[UUID],
    ) -> list[tuple[EvidenceSpanRecord, DocumentRecord, DocumentVersionRecord]]: ...

    def search_retrievable_spans(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
        query: str,
        candidate_limit: int,
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

    def corpus_release_id(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
    ) -> str: ...

    def object_inventory(self) -> dict[str, set[str]]: ...

    def healthcheck(self) -> bool: ...

    def readiness_snapshot(
        self, *, max_pending_events: int, max_pending_age_seconds: float
    ) -> dict[str, object]: ...

    def reconcile_audit_anchor(self, *, limit: int | None = None) -> int: ...

    def close(self) -> None: ...


class ObjectStore(Protocol):
    def put(self, content: bytes, source_hash: str, filename: str) -> str: ...

    def put_path(self, path: Path, source_hash: str, filename: str) -> str: ...

    def get(self, object_key: str) -> bytes: ...

    def get_to_path(self, object_key: str, destination: Path) -> None: ...

    def exists(self, object_key: str) -> bool: ...

    def healthcheck(self) -> bool: ...

    def list_keys(self) -> set[str]: ...

    def close(self) -> None: ...


class Retriever(Protocol):
    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int = 8,
    ) -> list[RetrievedEvidence]: ...
