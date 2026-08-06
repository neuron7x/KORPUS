from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from korpus.domain.models import (
    AccessTier,
    AuditVerification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    ExtractedPage,
    Identity,
    IngestionJobRecord,
    IngestResult,
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
        revision: str | None = None,
    ) -> DocumentVersionRecord | None: ...

    def transition_version(
        self,
        actor: Identity,
        version_id: UUID,
        expected_state: ReviewState,
        target_state: ReviewState,
        note: str,
        # Keyword-only. Two adjacent booleans in positional slots are one transposition
        # away from recording that a reviewer acknowledged a near-duplicate when what
        # they acknowledged was extraction quality — and the wrong one lands in the
        # audit chain as their assertion, where it cannot be edited.
        *,
        acknowledge_near_duplicate: bool = False,
        acknowledge_extraction_quality: bool = False,
        reviewer_credential_id: str | None = None,
        access_tier: AccessTier | None = None,
    ) -> DocumentVersionRecord: ...

    def list_retrievable_spans(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
        version_id: UUID | None = None,
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


class Extractor(Protocol):
    """Turning an uploaded file into pages, and pages into spans.

    Parsing is infrastructure: it shells out to `file(1)`, runs tesseract, and forks a
    resource-limited child. `application/ingestion.py` imported those three functions
    directly, which is the second half of the one dependency inversion this tree had.

    The cost is not abstraction purity. `IngestionService` decides *which* of the two
    extraction paths to take from `parser_sandbox_enabled`, and that decision is the
    application's — it is about whether untrusted bytes may be parsed in-process. With
    the concrete functions imported, the decision and the mechanism sat in one place and
    a test of the decision needed a real parser, an OCR binary and a fork.
    """

    def extract_pages(
        self,
        *,
        path: Path,
        filename: str,
        mime_type: str,
        sandboxed: bool,
        ocr_enabled: bool,
        ocr_languages: str,
        max_pdf_pages: int,
        ocr_total_timeout_seconds: int,
        timeout_seconds: int,
        memory_limit_mb: int,
        output_limit_bytes: int,
    ) -> tuple[list[ExtractedPage], str]: ...

    def make_spans(
        self,
        pages: list[ExtractedPage],
        *,
        max_chars: int,
        overlap_chars: int,
        max_spans: int,
    ) -> list[dict[str, object]]: ...


class IngestionJobQueue(Protocol):
    """The durable queue, as the application uses it.

    `application/ingestion_jobs.py` imported `SqlIngestionJobQueue` and `SqlRepository`
    directly — the one dependency inversion in this tree, and it was pointed at the two
    classes that hold every transaction and every row-level-security session. The port
    already existed for the repository and went unused; this is its other half.

    The inversion is not a style complaint. `IngestionCoordinator` is where a job is
    created and its audit event appended, and testing that pairing against the real
    SQLAlchemy classes means a database is required to exercise a rule that is about
    ordering. Worse, the import makes the layering unenforceable: nothing stops the next
    method from reaching for `queue.engine` and opening its own connection outside the
    session context that sets the RLS identity.
    """

    def create(self, actor: Identity, job: IngestionJobRecord) -> IngestionJobRecord: ...

    def get(self, identity: Identity, job_id: UUID) -> IngestionJobRecord | None: ...

    def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> IngestionJobRecord | None: ...

    def complete(
        self,
        worker_id: str,
        job_id: UUID,
        result: IngestResult,
        *,
        now: datetime | None = None,
    ) -> IngestionJobRecord: ...

    def fail(
        self,
        worker_id: str,
        job_id: UUID,
        error_code: str,
        error_detail: str,
        *,
        retryable: bool,
        now: datetime | None = None,
    ) -> IngestionJobRecord: ...


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
