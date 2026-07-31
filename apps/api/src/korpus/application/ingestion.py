from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from korpus.application.ports import ObjectStore, Repository
from korpus.application.policy import PolicyEngine
from korpus.domain.models import (
    DocumentCreate,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    IngestResult,
    ReviewState,
    ReviewTransition,
    VersionCreate,
)
from korpus.infrastructure.extraction import extract_pages, make_spans


ALLOWED_TRANSITIONS: dict[ReviewState, frozenset[ReviewState]] = {
    ReviewState.QUARANTINED: frozenset({ReviewState.METADATA_REVIEWED, ReviewState.REJECTED}),
    ReviewState.METADATA_REVIEWED: frozenset({ReviewState.CONTENT_REVIEWED, ReviewState.REJECTED}),
    ReviewState.CONTENT_REVIEWED: frozenset({ReviewState.APPROVED, ReviewState.REJECTED}),
    ReviewState.APPROVED: frozenset({ReviewState.REJECTED}),
    ReviewState.REJECTED: frozenset(),
}


@dataclass(frozen=True)
class ExtractionSettings:
    ocr_enabled: bool
    ocr_languages: str


class IngestionService:
    def __init__(
        self,
        repository: Repository,
        object_store: ObjectStore,
        policy: PolicyEngine,
        extraction: ExtractionSettings,
    ) -> None:
        self.repository = repository
        self.object_store = object_store
        self.policy = policy
        self.extraction = extraction

    def ingest(
        self,
        actor: Identity,
        document_data: DocumentCreate,
        version_data: VersionCreate,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> IngestResult:
        """Create a new canonical document and its first immutable version."""
        self.policy.require(actor, "document:ingest")
        if document_data.corpus_id not in actor.corpora and not actor.has_role("admin"):
            raise PermissionError("actor cannot ingest into unassigned corpus")
        digest = self._validate_and_hash(content)
        duplicate = self.repository.find_version_by_hash(digest)
        if duplicate is not None:
            duplicate_document = self.repository.get_document(duplicate.document_id)
            if (
                duplicate_document is None
                or not self.policy.can_access_document(actor, duplicate_document).allowed
                or duplicate_document.corpus_id != document_data.corpus_id
            ):
                raise ValueError("duplicate source content already exists")
            return IngestResult(
                document=duplicate_document,
                version=duplicate,
                span_count=0,
                extraction_method="deduplicated",
                duplicate=True,
            )

        page_spans, method = self._extract(content, filename, mime_type)
        document = DocumentRecord(**document_data.model_dump())
        version, spans = self._build_version_and_spans(
            document.id,
            version_data,
            content,
            filename,
            mime_type,
            digest,
            page_spans,
        )
        self.repository.create_document_bundle(document, version, spans)
        self._audit_ingest(actor, document, version, len(spans), method)
        return IngestResult(document=document, version=version, span_count=len(spans), extraction_method=method)

    def ingest_version(
        self,
        actor: Identity,
        document_id: UUID,
        version_data: VersionCreate,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> IngestResult:
        """Add an immutable version to an existing canonical document."""
        self.policy.require(actor, "document:ingest")
        document = self.repository.get_document(document_id)
        if document is None:
            raise LookupError("document not found")
        if not self.policy.can_access_document(actor, document).allowed:
            raise PermissionError("actor cannot access target document")
        digest = self._validate_and_hash(content)
        duplicate = self.repository.find_version_by_hash(digest)
        if duplicate is not None:
            if duplicate.document_id != document.id:
                raise ValueError("duplicate source content already exists")
            return IngestResult(
                document=document,
                version=duplicate,
                span_count=0,
                extraction_method="deduplicated",
                duplicate=True,
            )
        if version_data.supersedes_version_id is not None:
            superseded = self.repository.get_version(version_data.supersedes_version_id)
            if superseded is None or superseded.document_id != document.id:
                raise ValueError("supersedes_version_id must reference the same canonical document")

        page_spans, method = self._extract(content, filename, mime_type)
        version, spans = self._build_version_and_spans(
            document.id,
            version_data,
            content,
            filename,
            mime_type,
            digest,
            page_spans,
        )
        self.repository.create_version_bundle(version, spans)
        self._audit_ingest(actor, document, version, len(spans), method)
        return IngestResult(document=document, version=version, span_count=len(spans), extraction_method=method)

    def transition(
        self,
        actor: Identity,
        version_id: UUID,
        transition: ReviewTransition,
    ) -> DocumentVersionRecord:
        version = self.repository.get_version(version_id)
        if version is None:
            raise LookupError("version not found")
        permission = (
            "document:review_metadata"
            if transition.target is ReviewState.METADATA_REVIEWED
            else "document:review"
        )
        if transition.target is ReviewState.APPROVED:
            permission = "document:approve"
        self.policy.require(actor, permission)
        if transition.target not in ALLOWED_TRANSITIONS[version.review_state]:
            raise ValueError(
                f"invalid review transition {version.review_state.value} -> {transition.target.value}"
            )
        if transition.target is ReviewState.APPROVED and version.authority.value == "unknown":
            raise ValueError("unknown authority cannot be approved")
        updated = version.model_copy(update={"review_state": transition.target})
        self.repository.update_version(updated)
        self.repository.append_audit(
            actor,
            "document.review_transition",
            "document_version",
            str(version_id),
            {"from": version.review_state.value, "to": transition.target.value, "note": transition.note},
        )
        return updated

    @staticmethod
    def _validate_and_hash(content: bytes) -> str:
        if not content:
            raise ValueError("empty document")
        return sha256(content).hexdigest()

    def _extract(self, content: bytes, filename: str, mime_type: str) -> tuple[list[dict[str, object]], str]:
        pages, method = extract_pages(
            content=content,
            filename=filename,
            mime_type=mime_type,
            ocr_enabled=self.extraction.ocr_enabled,
            ocr_languages=self.extraction.ocr_languages,
        )
        return make_spans(pages), method

    def _build_version_and_spans(
        self,
        document_id: UUID,
        version_data: VersionCreate,
        content: bytes,
        filename: str,
        mime_type: str,
        digest: str,
        page_spans: list[dict[str, object]],
    ) -> tuple[DocumentVersionRecord, list[EvidenceSpanRecord]]:
        object_key = self.object_store.put(content, digest, Path(filename).name)
        version = DocumentVersionRecord(
            document_id=document_id,
            source_hash=digest,
            object_key=object_key,
            mime_type=mime_type,
            **version_data.model_dump(),
        )
        spans = [EvidenceSpanRecord(version_id=version.id, **span) for span in page_spans]
        return version, spans

    def _audit_ingest(
        self,
        actor: Identity,
        document: DocumentRecord,
        version: DocumentVersionRecord,
        span_count: int,
        method: str,
    ) -> None:
        self.repository.append_audit(
            actor,
            "document.ingested",
            "document_version",
            str(version.id),
            {
                "document_id": str(document.id),
                "source_hash": version.source_hash,
                "span_count": span_count,
                "extraction_method": method,
                "review_state": version.review_state.value,
                "supersedes_version_id": str(version.supersedes_version_id) if version.supersedes_version_id else None,
            },
        )
