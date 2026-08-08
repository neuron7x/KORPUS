from __future__ import annotations

import threading
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    Text,
    and_,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Engine

from korpus.domain.models import (
    DocumentCreate,
    Identity,
    IngestionJobKind,
    IngestionJobRecord,
    IngestionJobState,
    IngestResult,
    VersionCreate,
)
from korpus.infrastructure.repository import metadata

ingestion_jobs = Table(
    "ingestion_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("kind", String(32), nullable=False),
    Column("actor_subject", String(200), nullable=False, index=True),
    Column("actor_json", Text, nullable=False),
    Column("document_json", Text),
    Column("document_id", String(36)),
    Column("version_json", Text, nullable=False),
    Column("filename", String(500), nullable=False),
    Column("mime_type", String(200), nullable=False),
    Column("source_hash", String(64), nullable=False),
    Column("staging_object_key", Text, nullable=False),
    Column("state", String(32), nullable=False, index=True),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("lease_owner", String(200)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("result_json", Text),
    Column("error_code", String(200)),
    Column("error_detail", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index(
    "ix_ingestion_jobs_claim",
    ingestion_jobs.c.state,
    ingestion_jobs.c.lease_expires_at,
    ingestion_jobs.c.created_at,
)


class IngestionJobConflict(RuntimeError):
    pass


class SqlIngestionJobQueue:
    """Durable, lease-based ingestion queue.

    API requests only stage immutable bytes and create a job. Parser/OCR execution is
    delegated to a worker process. Claims are exclusive, expire, and are retry-bounded.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sqlite_lock = threading.RLock()

    @staticmethod
    def _apply_identity(connection: Any, identity: Identity) -> None:
        if connection.dialect.name != "postgresql":
            return
        connection.execute(
            select(
                func.set_config("korpus.subject", identity.subject, True),
                func.set_config("korpus.roles", ",".join(sorted(identity.roles)), True),
            )
        )

    def create(self, actor: Identity, job: IngestionJobRecord) -> IngestionJobRecord:
        if job.actor.subject != actor.subject:
            raise ValueError("job actor must match authenticated actor")
        values = self._values(job)
        with self.engine.begin() as connection:
            self._apply_identity(connection, actor)
            connection.execute(insert(ingestion_jobs).values(**values))
        return job

    def get(self, identity: Identity, job_id: UUID) -> IngestionJobRecord | None:
        with self.engine.begin() as connection:
            self._apply_identity(connection, identity)
            row = connection.execute(
                select(ingestion_jobs).where(ingestion_jobs.c.id == str(job_id))
            ).mappings().first()
        if row is None:
            return None
        if row["actor_subject"] != identity.subject and not identity.has_role("admin", "auditor"):
            return None
        return self._record(row)

    def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> IngestionJobRecord | None:
        if not worker_id.strip() or lease_seconds < 5:
            raise ValueError("invalid worker lease")
        current = now or datetime.now(UTC)
        guard = self._sqlite_lock if self.engine.dialect.name == "sqlite" else nullcontext()
        with guard, self.engine.begin() as connection:
            worker = Identity(
                subject=worker_id,
                roles=frozenset({"worker"}),
                corpora=frozenset({"public"}),
            )
            self._apply_identity(connection, worker)
            eligible = or_(
                ingestion_jobs.c.state == IngestionJobState.QUEUED.value,
                ingestion_jobs.c.state == IngestionJobState.RETRYABLE.value,
                and_(
                    ingestion_jobs.c.state == IngestionJobState.RUNNING.value,
                    ingestion_jobs.c.lease_expires_at.is_not(None),
                    ingestion_jobs.c.lease_expires_at < current,
                ),
            )
            statement = (
                select(ingestion_jobs)
                .where(eligible)
                .where(ingestion_jobs.c.attempts < ingestion_jobs.c.max_attempts)
                .order_by(ingestion_jobs.c.created_at, ingestion_jobs.c.id)
                .limit(1)
            )
            if connection.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            row = connection.execute(statement).mappings().first()
            if row is None:
                return None
            result = connection.execute(
                update(ingestion_jobs)
                .where(ingestion_jobs.c.id == row["id"])
                .where(ingestion_jobs.c.state == row["state"])
                .where(ingestion_jobs.c.attempts == row["attempts"])
                .values(
                    state=IngestionJobState.RUNNING.value,
                    attempts=int(row["attempts"]) + 1,
                    lease_owner=worker_id,
                    lease_expires_at=current + timedelta(seconds=lease_seconds),
                    error_code=None,
                    error_detail=None,
                    updated_at=current,
                )
            )
            if result.rowcount != 1:
                raise IngestionJobConflict("ingestion job claim changed concurrently")
            updated = connection.execute(
                select(ingestion_jobs).where(ingestion_jobs.c.id == row["id"])
            ).mappings().one()
            return self._record(updated)

    def complete(
        self,
        worker_id: str,
        job_id: UUID,
        result: IngestResult,
        *,
        now: datetime | None = None,
    ) -> IngestionJobRecord:
        current = now or datetime.now(UTC)
        with self.engine.begin() as connection:
            worker = Identity(
                subject=worker_id, roles=frozenset({"worker"}), corpora=frozenset({"public"})
            )
            self._apply_identity(connection, worker)
            changed = connection.execute(
                update(ingestion_jobs)
                .where(ingestion_jobs.c.id == str(job_id))
                .where(ingestion_jobs.c.state == IngestionJobState.RUNNING.value)
                .where(ingestion_jobs.c.lease_owner == worker_id)
                .values(
                    state=IngestionJobState.SUCCEEDED.value,
                    result_json=result.model_dump_json(),
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=current,
                )
            )
            if changed.rowcount != 1:
                raise IngestionJobConflict("worker does not own active ingestion lease")
            row = connection.execute(
                select(ingestion_jobs).where(ingestion_jobs.c.id == str(job_id))
            ).mappings().one()
        return self._record(row)

    def fail(
        self,
        worker_id: str,
        job_id: UUID,
        error_code: str,
        error_detail: str,
        *,
        retryable: bool,
        now: datetime | None = None,
    ) -> IngestionJobRecord:
        current = now or datetime.now(UTC)
        with self.engine.begin() as connection:
            worker = Identity(
                subject=worker_id, roles=frozenset({"worker"}), corpora=frozenset({"public"})
            )
            self._apply_identity(connection, worker)
            row = connection.execute(
                select(ingestion_jobs)
                .where(ingestion_jobs.c.id == str(job_id))
                .where(ingestion_jobs.c.state == IngestionJobState.RUNNING.value)
                .where(ingestion_jobs.c.lease_owner == worker_id)
            ).mappings().first()
            if row is None:
                raise IngestionJobConflict("worker does not own active ingestion lease")
            target = (
                IngestionJobState.RETRYABLE
                if retryable and int(row["attempts"]) < int(row["max_attempts"])
                else IngestionJobState.DEAD_LETTER
            )
            connection.execute(
                update(ingestion_jobs)
                .where(ingestion_jobs.c.id == str(job_id))
                .where(ingestion_jobs.c.lease_owner == worker_id)
                .values(
                    state=target.value,
                    lease_owner=None,
                    lease_expires_at=None,
                    error_code=error_code[:200],
                    error_detail=error_detail[:2000],
                    updated_at=current,
                )
            )
            updated = connection.execute(
                select(ingestion_jobs).where(ingestion_jobs.c.id == str(job_id))
            ).mappings().one()
        return self._record(updated)

    def reap_orphaned_leases(self, *, now: datetime | None = None) -> list[IngestionJobRecord]:
        """Terminate jobs a crashed worker left RUNNING that can never be re-claimed.

        `claim` re-picks a RUNNING job once its lease expires, but only while attempts are
        below the ceiling — so a worker that dies mid-job on the last attempt leaves the
        row RUNNING with an expired lease and attempts at the max: never re-claimed, never
        failed, never audited. A soldier's document sits in that state forever with no
        record of why. This moves those rows to DEAD_LETTER and returns them so the caller
        can write the audit event the crashed worker never got to.

        Scoped to expired-lease-and-exhausted: a job still within its lease belongs to a
        live worker, and one with attempts left is `claim`'s job, not the reaper's.
        """
        current = now or datetime.now(UTC)
        reaped: list[IngestionJobRecord] = []
        with self.engine.begin() as connection:
            worker = Identity(
                subject="reaper", roles=frozenset({"worker"}), corpora=frozenset({"public"})
            )
            self._apply_identity(connection, worker)
            orphans = connection.execute(
                select(ingestion_jobs)
                .where(ingestion_jobs.c.state == IngestionJobState.RUNNING.value)
                .where(ingestion_jobs.c.lease_expires_at.is_not(None))
                .where(ingestion_jobs.c.lease_expires_at < current)
                .where(ingestion_jobs.c.attempts >= ingestion_jobs.c.max_attempts)
            ).mappings().all()
            for row in orphans:
                changed = connection.execute(
                    update(ingestion_jobs)
                    # Re-assert the RUNNING state and the exact lease in the WHERE so a
                    # worker that revived and completed between the SELECT and here is not
                    # overwritten: the reaper never wins a race against real progress.
                    .where(ingestion_jobs.c.id == row["id"])
                    .where(ingestion_jobs.c.state == IngestionJobState.RUNNING.value)
                    .where(ingestion_jobs.c.lease_expires_at == row["lease_expires_at"])
                    .values(
                        state=IngestionJobState.DEAD_LETTER.value,
                        lease_owner=None,
                        lease_expires_at=None,
                        error_code="orphaned_lease",
                        error_detail="worker lease expired with attempts exhausted; reaped",
                        updated_at=current,
                    )
                )
                if changed.rowcount == 1:
                    updated = connection.execute(
                        select(ingestion_jobs).where(ingestion_jobs.c.id == row["id"])
                    ).mappings().one()
                    reaped.append(self._record(updated))
        return reaped

    @staticmethod
    def _values(job: IngestionJobRecord) -> dict[str, Any]:
        return {
            "id": str(job.id),
            "kind": job.kind.value,
            "actor_subject": job.actor.subject,
            "actor_json": job.actor.model_dump_json(),
            "document_json": job.document.model_dump_json() if job.document else None,
            "document_id": str(job.document_id) if job.document_id else None,
            "version_json": job.version.model_dump_json(),
            "filename": job.filename,
            "mime_type": job.mime_type,
            "source_hash": job.source_hash,
            "staging_object_key": job.staging_object_key,
            "state": job.state.value,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "lease_owner": job.lease_owner,
            "lease_expires_at": job.lease_expires_at,
            "result_json": job.result.model_dump_json() if job.result else None,
            "error_code": job.error_code,
            "error_detail": job.error_detail,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }

    @staticmethod
    def _record(row: Any) -> IngestionJobRecord:
        return IngestionJobRecord(
            id=UUID(row["id"]),
            kind=IngestionJobKind(row["kind"]),
            actor=Identity.model_validate_json(row["actor_json"]),
            document=(
                DocumentCreate.model_validate_json(row["document_json"])
                if row["document_json"]
                else None
            ),
            document_id=UUID(row["document_id"]) if row["document_id"] else None,
            version=VersionCreate.model_validate_json(row["version_json"]),
            filename=row["filename"],
            mime_type=row["mime_type"],
            source_hash=row["source_hash"],
            staging_object_key=row["staging_object_key"],
            state=IngestionJobState(row["state"]),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            result=(
                IngestResult.model_validate_json(row["result_json"]) if row["result_json"] else None
            ),
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
