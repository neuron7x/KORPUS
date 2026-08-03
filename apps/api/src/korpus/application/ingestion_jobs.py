from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from korpus.application.ingestion import IngestionService
from korpus.application.policy import PolicyEngine
from korpus.application.ports import ObjectStore
from korpus.domain.models import (
    DocumentCreate,
    Identity,
    IngestionJobKind,
    IngestionJobRecord,
    VersionCreate,
)
from korpus.infrastructure.ingestion_jobs import SqlIngestionJobQueue
from korpus.infrastructure.repository import SqlRepository
from korpus.security.scanning import MalwareDetectedError, MalwareScannerUnavailable


@dataclass(frozen=True)
class JobExecution:
    claimed: bool
    job: IngestionJobRecord | None


class DurableIngestionCoordinator:
    def __init__(
        self,
        queue: SqlIngestionJobQueue,
        quarantine_store: ObjectStore,
        repository: SqlRepository,
        policy: PolicyEngine,
        *,
        max_attempts: int,
    ) -> None:
        self.queue = queue
        self.quarantine_store = quarantine_store
        self.repository = repository
        self.policy = policy
        self.max_attempts = max_attempts

    def submit_document(
        self,
        actor: Identity,
        document: DocumentCreate,
        version: VersionCreate,
        *,
        filename: str,
        mime_type: str,
        path: Path,
        source_hash: str,
    ) -> IngestionJobRecord:
        self.policy.require(actor, "document:ingest")
        if document.corpus_id not in actor.corpora and not actor.has_role("admin"):
            raise PermissionError("actor cannot ingest into unassigned corpus")
        if not document.compartments.issubset(actor.compartments) and not actor.has_role("admin"):
            raise PermissionError("actor cannot assign unowned compartments")
        key = self.quarantine_store.put_path(path, source_hash, filename)
        job = IngestionJobRecord(
            kind=IngestionJobKind.DOCUMENT,
            actor=actor,
            document=document,
            version=version,
            filename=filename,
            mime_type=mime_type,
            source_hash=source_hash,
            staging_object_key=key,
            max_attempts=self.max_attempts,
        )
        self.queue.create(actor, job)
        self.repository.append_audit(
            actor,
            "ingestion.job_submitted",
            "ingestion_job",
            str(job.id),
            {
                "kind": job.kind.value,
                "source_hash": source_hash,
                "corpus_id": document.corpus_id,
                "compartments": sorted(document.compartments),
            },
        )
        return job

    def submit_version(
        self,
        actor: Identity,
        document_id: UUID,
        version: VersionCreate,
        *,
        filename: str,
        mime_type: str,
        path: Path,
        source_hash: str,
    ) -> IngestionJobRecord:
        self.policy.require(actor, "document:ingest")
        document = self.repository.get_document(actor, document_id)
        if document is None:
            raise LookupError("document not found")
        key = self.quarantine_store.put_path(path, source_hash, filename)
        job = IngestionJobRecord(
            kind=IngestionJobKind.VERSION,
            actor=actor,
            document_id=document_id,
            version=version,
            filename=filename,
            mime_type=mime_type,
            source_hash=source_hash,
            staging_object_key=key,
            max_attempts=self.max_attempts,
        )
        self.queue.create(actor, job)
        self.repository.append_audit(
            actor,
            "ingestion.job_submitted",
            "ingestion_job",
            str(job.id),
            {
                "kind": job.kind.value,
                "source_hash": source_hash,
                "document_id": str(document_id),
            },
        )
        return job

    def get(self, identity: Identity, job_id: UUID) -> IngestionJobRecord | None:
        return self.queue.get(identity, job_id)


class IngestionWorker:
    def __init__(
        self,
        queue: SqlIngestionJobQueue,
        quarantine_store: ObjectStore,
        ingestion: IngestionService,
        repository: SqlRepository,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        self.queue = queue
        self.quarantine_store = quarantine_store
        self.ingestion = ingestion
        self.repository = repository
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    def run_once(self) -> JobExecution:
        job = self.queue.claim(self.worker_id, lease_seconds=self.lease_seconds)
        if job is None:
            return JobExecution(False, None)
        suffix = Path(job.filename).suffix[:16]
        with tempfile.TemporaryDirectory(prefix="korpus-job-") as directory:
            path = Path(directory) / f"payload{suffix}"
            try:
                self.quarantine_store.get_to_path(job.staging_object_key, path)
                if job.kind is IngestionJobKind.DOCUMENT:
                    assert job.document is not None
                    result = self.ingestion.ingest_path(
                        job.actor,
                        job.document,
                        job.version,
                        job.filename,
                        job.mime_type,
                        path,
                        job.source_hash,
                    )
                else:
                    assert job.document_id is not None
                    result = self.ingestion.ingest_version_path(
                        job.actor,
                        job.document_id,
                        job.version,
                        job.filename,
                        job.mime_type,
                        path,
                        job.source_hash,
                    )
                completed = self.queue.complete(self.worker_id, job.id, result)
                self.repository.append_audit(
                    job.actor,
                    "ingestion.job_succeeded",
                    "ingestion_job",
                    str(job.id),
                    {"document_id": str(result.document.id), "version_id": str(result.version.id)},
                )
                return JobExecution(True, completed)
            except (MalwareDetectedError, ValueError, PermissionError, LookupError) as exc:
                failed = self.queue.fail(
                    self.worker_id,
                    job.id,
                    type(exc).__name__,
                    str(exc),
                    retryable=False,
                )
            except (MalwareScannerUnavailable, OSError, TimeoutError, RuntimeError) as exc:
                failed = self.queue.fail(
                    self.worker_id,
                    job.id,
                    type(exc).__name__,
                    str(exc),
                    retryable=True,
                )
            self.repository.append_audit(
                job.actor,
                "ingestion.job_failed",
                "ingestion_job",
                str(job.id),
                {"state": failed.state.value, "error_code": failed.error_code},
            )
            return JobExecution(True, failed)
