from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from korpus.application.extraction_quality import ExtractionQuality, assess_extraction_quality
from korpus.application.fingerprints import simhash64
from korpus.application.policy import PolicyEngine
from korpus.application.ports import ObjectStore, Repository
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
from korpus.infrastructure.extraction import (
    extract_pages_from_path,
    extract_pages_sandboxed,
    make_spans,
)
from korpus.security.corpus_governance import CorpusGovernanceProfile
from korpus.security.reviewers import ReviewerRegistry
from korpus.security.scanning import DisabledMalwareScanner, MalwareScanner
from korpus.security.source_authenticity import SourceTrustProfile

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
    max_pdf_pages: int = 500
    max_spans_per_document: int = 20_000
    max_chunk_chars: int = 1400
    chunk_overlap_chars: int = 180
    ocr_total_timeout_seconds: int = 300
    parser_sandbox_enabled: bool = False
    parser_timeout_seconds: int = 120
    parser_memory_limit_mb: int = 768
    parser_output_limit_bytes: int = 64 * 1024 * 1024


class IngestionService:
    def __init__(
        self,
        repository: Repository,
        object_store: ObjectStore,
        policy: PolicyEngine,
        extraction: ExtractionSettings,
        review_separation_required: bool = False,
        malware_scanner: MalwareScanner | None = None,
        source_trust_profile: SourceTrustProfile | None = None,
        require_source_signature: bool = False,
        reviewer_registry: ReviewerRegistry | None = None,
        require_reviewer_credentials: bool = False,
        corpus_governance: CorpusGovernanceProfile | None = None,
        require_corpus_governance: bool = False,
    ) -> None:
        self.repository = repository
        self.object_store = object_store
        self.policy = policy
        self.extraction = extraction
        self.review_separation_required = review_separation_required
        self.malware_scanner = malware_scanner or DisabledMalwareScanner()
        self.source_trust_profile = source_trust_profile
        self.require_source_signature = require_source_signature
        self.reviewer_registry = reviewer_registry
        self.require_reviewer_credentials = require_reviewer_credentials
        self.corpus_governance = corpus_governance
        self.require_corpus_governance = require_corpus_governance
        if require_corpus_governance and corpus_governance is None:
            raise ValueError("controlled ingestion requires a corpus governance profile")
        if require_reviewer_credentials and reviewer_registry is None:
            raise ValueError("reviewer credential enforcement requires a registry")
        if require_source_signature and source_trust_profile is None:
            raise ValueError("source signature enforcement requires a trust profile")

    def ingest(
        self,
        actor: Identity,
        document_data: DocumentCreate,
        version_data: VersionCreate,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> IngestResult:
        with tempfile.NamedTemporaryFile(
            prefix="korpus-ingest-", suffix=Path(filename).suffix, delete=False
        ) as handle:
            handle.write(content)
            path = Path(handle.name)
        try:
            return self.ingest_path(
                actor,
                document_data,
                version_data,
                filename,
                mime_type,
                path,
                hashlib.sha256(content).hexdigest(),
            )
        finally:
            path.unlink(missing_ok=True)

    def ingest_path(
        self,
        actor: Identity,
        document_data: DocumentCreate,
        version_data: VersionCreate,
        filename: str,
        mime_type: str,
        path: Path,
        source_hash: str | None = None,
    ) -> IngestResult:
        self.policy.require(actor, "document:ingest")
        if self.corpus_governance is not None:
            self.corpus_governance.authorize_ingestion(
                document_data, version_data, ocr_requested=self.extraction.ocr_enabled
            )
        elif self.require_corpus_governance:
            raise PermissionError("corpus governance profile is unavailable")
        if document_data.corpus_id not in actor.corpora and not actor.has_role("admin"):
            raise PermissionError("actor cannot ingest into unassigned corpus")
        if not document_data.compartments.issubset(actor.compartments) and not actor.has_role(
            "admin"
        ):
            raise PermissionError("actor cannot assign unowned compartments")
        digest = self._validate_path_and_hash(path, source_hash)
        self._verify_source(document_data.issuer, version_data, digest)
        duplicate = self.repository.find_version_by_hash(
            actor, digest, corpus_id=document_data.corpus_id, revision=version_data.revision
        )
        if duplicate is not None:
            duplicate_document = self.repository.get_document(actor, duplicate.document_id)
            if (
                duplicate_document is None
                or not self.policy.can_access_document(actor, duplicate_document).allowed
            ):
                raise ValueError("duplicate source content already exists")
            return IngestResult(
                document=duplicate_document,
                version=duplicate,
                span_count=0,
                extraction_method="deduplicated",
                duplicate=True,
            )
        self.malware_scanner.scan(path)
        page_spans, method = self._extract_path(path, filename, mime_type)
        extracted_text = "\n".join(str(span["text"]) for span in page_spans)
        fingerprint = simhash64(extracted_text)
        quality = assess_extraction_quality(extracted_text)
        near_duplicate = self.repository.find_near_duplicate(
            actor, fingerprint, corpus_id=document_data.corpus_id
        )
        document = DocumentRecord(**document_data.model_dump())
        version, spans = self._build_version_and_spans_path(
            document.id, version_data, path, filename, mime_type, digest, page_spans,
            content_fingerprint=fingerprint,
            near_duplicate=near_duplicate,
            extraction_quality=quality,
        )
        audit_payload = self._ingest_audit_payload(document, version, len(spans), method)
        self.repository.create_document_bundle(actor, document, version, spans, audit_payload)
        return IngestResult(
            document=document,
            version=version,
            span_count=len(spans),
            extraction_method=method,
        )

    def ingest_version(
        self,
        actor: Identity,
        document_id: UUID,
        version_data: VersionCreate,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> IngestResult:
        with tempfile.NamedTemporaryFile(
            prefix="korpus-ingest-", suffix=Path(filename).suffix, delete=False
        ) as handle:
            handle.write(content)
            path = Path(handle.name)
        try:
            return self.ingest_version_path(
                actor,
                document_id,
                version_data,
                filename,
                mime_type,
                path,
                hashlib.sha256(content).hexdigest(),
            )
        finally:
            path.unlink(missing_ok=True)

    def ingest_version_path(
        self,
        actor: Identity,
        document_id: UUID,
        version_data: VersionCreate,
        filename: str,
        mime_type: str,
        path: Path,
        source_hash: str | None = None,
    ) -> IngestResult:
        self.policy.require(actor, "document:ingest")
        document = self.repository.get_document(actor, document_id)
        if document is None:
            raise LookupError("document not found")
        if not self.policy.can_access_document(actor, document).allowed:
            raise PermissionError("actor cannot access target document")
        if self.corpus_governance is not None:
            self.corpus_governance.authorize_ingestion(
                DocumentCreate(**document.model_dump(exclude={"id", "created_at"})),
                version_data,
                ocr_requested=self.extraction.ocr_enabled,
            )
        elif self.require_corpus_governance:
            raise PermissionError("corpus governance profile is unavailable")
        digest = self._validate_path_and_hash(path, source_hash)
        self._verify_source(document.issuer, version_data, digest)
        duplicate = self.repository.find_version_by_hash(
            actor, digest, document_id=document.id, revision=version_data.revision
        )
        if duplicate is not None:
            return IngestResult(
                document=document,
                version=duplicate,
                span_count=0,
                extraction_method="deduplicated",
                duplicate=True,
            )
        if version_data.supersedes_version_id is not None:
            superseded = self.repository.get_version(actor, version_data.supersedes_version_id)
            if superseded is None or superseded.document_id != document.id:
                raise ValueError("supersedes_version_id must reference the same canonical document")
        self.malware_scanner.scan(path)
        page_spans, method = self._extract_path(path, filename, mime_type)
        extracted_text = "\n".join(str(span["text"]) for span in page_spans)
        fingerprint = simhash64(extracted_text)
        quality = assess_extraction_quality(extracted_text)
        near_duplicate = self.repository.find_near_duplicate(
            actor, fingerprint, document_id=document.id
        )
        version, spans = self._build_version_and_spans_path(
            document.id, version_data, path, filename, mime_type, digest, page_spans,
            content_fingerprint=fingerprint,
            near_duplicate=near_duplicate,
            extraction_quality=quality,
        )
        audit_payload = self._ingest_audit_payload(document, version, len(spans), method)
        self.repository.create_version_bundle(actor, version, spans, audit_payload)
        return IngestResult(
            document=document,
            version=version,
            span_count=len(spans),
            extraction_method=method,
        )

    def transition(
        self,
        actor: Identity,
        version_id: UUID,
        transition: ReviewTransition,
    ) -> DocumentVersionRecord:
        version = self.repository.get_version(actor, version_id)
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
                f"invalid review transition {version.review_state.value}"
                f" -> {transition.target.value}"
            )
        if transition.target is ReviewState.APPROVED and not version.authority.is_normative:
            raise ValueError(f"{version.authority.value} authority cannot be approved")
        if self.review_separation_required:
            if (
                transition.target is ReviewState.CONTENT_REVIEWED
                and version.metadata_reviewed_by == actor.subject
            ):
                raise ValueError("content reviewer must differ from metadata reviewer")
            if transition.target is ReviewState.APPROVED and actor.subject in {
                version.metadata_reviewed_by,
                version.content_reviewed_by,
            }:
                raise ValueError("approver must differ from prior reviewers")
        reviewer_credential_id: str | None = None
        if transition.target in {
            ReviewState.METADATA_REVIEWED,
            ReviewState.CONTENT_REVIEWED,
            ReviewState.APPROVED,
        }:
            document = self.repository.get_document(actor, version.document_id)
            if document is None:
                raise LookupError("document not found")
            if self.reviewer_registry is not None:
                reviewer_credential_id = self.reviewer_registry.authorize(
                    subject=actor.subject,
                    target=transition.target,
                    document=document,
                    version=version,
                )
            elif self.require_reviewer_credentials:
                raise PermissionError("reviewer credential registry is unavailable")
        return self.repository.transition_version(
            actor,
            version_id,
            expected_state=version.review_state,
            target_state=transition.target,
            note=transition.note,
            acknowledge_near_duplicate=transition.acknowledge_near_duplicate,
            acknowledge_extraction_quality=transition.acknowledge_extraction_quality,
            reviewer_credential_id=reviewer_credential_id,
            access_tier=transition.access_tier,
        )


    def _verify_source(self, issuer: str, version: VersionCreate, source_hash: str) -> None:
        supplied = bool(version.source_key_id or version.source_signature_b64)
        if not self.require_source_signature and not supplied:
            return
        if self.source_trust_profile is None:
            raise ValueError("source trust profile is unavailable")
        self.source_trust_profile.verify(issuer=issuer, version=version, source_hash=source_hash)

    @staticmethod
    def _validate_path_and_hash(path: Path, expected: str | None) -> str:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("empty document")
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        if expected is not None and digest != expected:
            raise ValueError("upload digest mismatch")
        return digest

    def _extract_path(
        self, path: Path, filename: str, mime_type: str
    ) -> tuple[list[dict[str, object]], str]:
        if self.extraction.parser_sandbox_enabled:
            pages, method = extract_pages_sandboxed(
                path=path,
                filename=filename,
                mime_type=mime_type,
                ocr_enabled=self.extraction.ocr_enabled,
                ocr_languages=self.extraction.ocr_languages,
                max_pdf_pages=self.extraction.max_pdf_pages,
                ocr_total_timeout_seconds=self.extraction.ocr_total_timeout_seconds,
                timeout_seconds=self.extraction.parser_timeout_seconds,
                memory_limit_mb=self.extraction.parser_memory_limit_mb,
                output_limit_bytes=self.extraction.parser_output_limit_bytes,
            )
        else:
            pages, method = extract_pages_from_path(
                path=path,
                filename=filename,
                mime_type=mime_type,
                ocr_enabled=self.extraction.ocr_enabled,
                ocr_languages=self.extraction.ocr_languages,
                max_pdf_pages=self.extraction.max_pdf_pages,
                ocr_total_timeout_seconds=self.extraction.ocr_total_timeout_seconds,
            )
        return (
            make_spans(
                pages,
                max_chars=self.extraction.max_chunk_chars,
                overlap_chars=self.extraction.chunk_overlap_chars,
                max_spans=self.extraction.max_spans_per_document,
            ),
            method,
        )

    def _build_version_and_spans_path(
        self,
        document_id: UUID,
        version_data: VersionCreate,
        path: Path,
        filename: str,
        mime_type: str,
        digest: str,
        page_spans: list[dict[str, object]],
        *,
        content_fingerprint: str,
        near_duplicate: tuple[DocumentVersionRecord, float] | None,
        extraction_quality: ExtractionQuality,
    ) -> tuple[DocumentVersionRecord, list[EvidenceSpanRecord]]:
        object_key = self.object_store.put_path(path, digest, Path(filename).name)
        version = DocumentVersionRecord(
            document_id=document_id,
            source_hash=digest,
            object_key=object_key,
            mime_type=mime_type,
            content_fingerprint=content_fingerprint,
            near_duplicate_of_version_id=near_duplicate[0].id if near_duplicate else None,
            near_duplicate_similarity=near_duplicate[1] if near_duplicate else None,
            extraction_text_chars=extraction_quality.text_chars,
            extraction_alnum_ratio=extraction_quality.alnum_ratio,
            extraction_replacement_ratio=extraction_quality.replacement_ratio,
            extraction_quality_flags=extraction_quality.flags,
            **version_data.model_dump(),
        )
        spans = [EvidenceSpanRecord(version_id=version.id, **span) for span in page_spans]
        return version, spans

    @staticmethod
    def _ingest_audit_payload(
        document: DocumentRecord,
        version: DocumentVersionRecord,
        span_count: int,
        method: str,
    ) -> dict[str, object]:
        return {
            "document_id": str(document.id),
            "source_hash": version.source_hash,
            "span_count": span_count,
            "extraction_method": method,
            "review_state": version.review_state.value,
            "compartments": sorted(document.compartments),
            "supersedes_version_id": (
                str(version.supersedes_version_id) if version.supersedes_version_id else None
            ),
            "content_fingerprint": version.content_fingerprint,
            "near_duplicate_of_version_id": (
                str(version.near_duplicate_of_version_id)
                if version.near_duplicate_of_version_id
                else None
            ),
            "near_duplicate_similarity": version.near_duplicate_similarity,
            "extraction_text_chars": version.extraction_text_chars,
            "extraction_alnum_ratio": version.extraction_alnum_ratio,
            "extraction_replacement_ratio": version.extraction_replacement_ratio,
            "extraction_quality_flags": sorted(version.extraction_quality_flags),
        }
