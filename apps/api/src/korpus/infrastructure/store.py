"""Durable corpus and audit store.

SQLite, from the standard library. The choice is deliberate rather than minimal:
the corpus must survive a restart, the audit trail must survive a crash, and a
system that a soldier depends on must not require a database cluster to answer a
question. PostgreSQL replaces this behind the same interface when the deployment
earns it (ADR-0001); nothing above this file knows which one is underneath.

Two properties are enforced here rather than hoped for:

* immutability — an approved chunk is never updated in place, only superseded;
* recoverability — the store checks its own integrity on open, and a corrupt file
  is quarantined and rebuilt from the append-only journal instead of taking the
  process down with it.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Citation,
    EvidenceSpan,
    ReviewState,
)

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id            TEXT PRIMARY KEY,
    document_id         TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    corpus_id           TEXT NOT NULL,
    title               TEXT NOT NULL,
    revision            TEXT,
    page                INTEGER,
    section             TEXT,
    quote               TEXT NOT NULL,
    source_uri          TEXT,
    text                TEXT NOT NULL,
    access_tier         TEXT NOT NULL,
    review_state        TEXT NOT NULL,
    authority           TEXT NOT NULL,
    valid_until         TEXT,
    superseded_by       TEXT,
    content_sha256      TEXT NOT NULL,
    ingested_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_by_corpus ON chunks (corpus_id);
CREATE INDEX IF NOT EXISTS chunks_by_version ON chunks (document_version_id);

CREATE TABLE IF NOT EXISTS audit (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded  TEXT NOT NULL,
    event     TEXT NOT NULL,
    payload   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_by_event ON audit (event);
"""

JOURNAL_NAME = "corpus-journal.jsonl"


class StoreUnavailable(RuntimeError):
    """Raised only where a caller can degrade; never allowed to reach a user."""


def _row_to_span(row: sqlite3.Row) -> EvidenceSpan:
    return EvidenceSpan(
        citation=Citation(
            document_id=UUID(row["document_id"]),
            chunk_id=UUID(row["chunk_id"]),
            title=row["title"],
            revision=row["revision"],
            page=row["page"],
            section=row["section"],
            quote=row["quote"],
            source_uri=row["source_uri"],
        ),
        chunk_id=UUID(row["chunk_id"]),
        document_id=UUID(row["document_id"]),
        document_version_id=UUID(row["document_version_id"]),
        corpus_id=UUID(row["corpus_id"]),
        text=row["text"],
        retrieval_score=0.0,
        access_tier=AccessTier(row["access_tier"]),
        review_state=ReviewState(row["review_state"]),
        authority=AuthorityClass(row["authority"]),
        valid_until=datetime.fromisoformat(row["valid_until"]) if row["valid_until"] else None,
        superseded_by=UUID(row["superseded_by"]) if row["superseded_by"] else None,
    )


def _span_to_row(span: EvidenceSpan, content_sha256: str, now: datetime) -> tuple[object, ...]:
    citation = span.citation
    return (
        str(span.chunk_id),
        str(span.document_id),
        str(span.document_version_id),
        str(span.corpus_id),
        citation.title,
        citation.revision,
        citation.page,
        citation.section,
        citation.quote,
        citation.source_uri,
        span.text,
        span.access_tier.value,
        span.review_state.value,
        span.authority.value,
        span.valid_until.isoformat() if span.valid_until else None,
        str(span.superseded_by) if span.superseded_by else None,
        content_sha256,
        now.isoformat(),
    )


class CorpusStore:
    """The one place that owns the database file."""

    def __init__(self, path: Path, journal: Path | None = None) -> None:
        self.path = path
        self.journal = journal or path.parent / JOURNAL_NAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.recovered = False
        self._lock = threading.RLock()
        self._connect()

    # ------------------------------------------------------------------ lifecycle

    def _open(self) -> sqlite3.Connection:
        # One connection shared across the server's worker threads, serialised by a
        # lock. `check_same_thread=False` without the lock would be a data race; the
        # lock without it would be a ProgrammingError on the first threadpool call.
        connection = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _connect(self) -> None:
        try:
            self._connection = self._open()
            self._connection.executescript(SCHEMA)
            self._verify_integrity()
        except sqlite3.DatabaseError as error:
            log.error("corpus store unusable (%s); rebuilding from journal", error)
            self._quarantine_and_rebuild()

    def _verify_integrity(self) -> None:
        with self._lock:
            result = self._connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise sqlite3.DatabaseError(f"integrity_check: {result[0] if result else 'no result'}")

    def _quarantine_and_rebuild(self) -> None:
        """A corrupt file is moved aside, not deleted, and the corpus is replayed.

        Deleting the evidence of a failure is how the same failure comes back
        unexplained. The quarantined file keeps its timestamp in the name.
        """
        if self.path.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            quarantine = self.path.with_suffix(f".corrupt-{stamp}")
            self.path.rename(quarantine)
            log.error("quarantined corrupt store at %s", quarantine)
        self._connection = self._open()
        self._connection.executescript(SCHEMA)
        self.recovered = True
        self.replay_journal()

    def close(self) -> None:
        with closing(self._connection):
            pass

    # ------------------------------------------------------------------- writing

    def add(self, span: EvidenceSpan, content_sha256: str, now: datetime | None = None) -> bool:
        """Insert a chunk. Returns False when the identical chunk is already stored.

        Ingesting the same document twice must not double every citation, so this is
        idempotent on chunk identity, which is derived from content.
        """
        moment = now or datetime.now(UTC)
        row = _span_to_row(span, content_sha256, moment)
        try:
            with self._lock:
                self._connection.execute(
                    "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row
                )
        except sqlite3.IntegrityError:
            return False
        record = json.loads(span.model_dump_json())
        record["op"] = "add"
        record["content_sha256"] = content_sha256
        record["ingested_at"] = moment.isoformat()
        self._append_journal(record)
        return True

    def _append_journal(self, record: dict[str, object]) -> None:
        """Append-only log of every accepted change, used to rebuild the database.

        Every operation is journalled, not only insertion: a review decision or a
        supersession that lived solely in the database would be lost by the very
        recovery that is supposed to preserve the corpus.
        """
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def approve(
        self,
        version_id: UUID,
        reviewer: str,
        access_tier: AccessTier | None = None,
        now: datetime | None = None,
    ) -> int:
        """Move every chunk of a version into `approved`, optionally re-tiering it.

        Approval is a state transition, not a re-import: chunk identity comes from
        content, so importing the same file again inserts nothing and would leave the
        document quarantined while the operator believed it had been released.
        """
        moment = now or datetime.now(UTC)
        with self._lock:
            if access_tier is None:
                cursor = self._connection.execute(
                    "UPDATE chunks SET review_state = ? WHERE document_version_id = ?",
                    (ReviewState.APPROVED.value, str(version_id)),
                )
            else:
                cursor = self._connection.execute(
                    "UPDATE chunks SET review_state = ?, access_tier = ? "
                    "WHERE document_version_id = ?",
                    (ReviewState.APPROVED.value, access_tier.value, str(version_id)),
                )
            changed = int(cursor.rowcount)
        if changed:
            self._append_journal(
                {
                    "op": "review",
                    "document_version_id": str(version_id),
                    "review_state": ReviewState.APPROVED.value,
                    "access_tier": access_tier.value if access_tier else None,
                    "reviewer": reviewer,
                    "at": moment.isoformat(),
                }
            )
        return changed

    def supersede(self, version_id: UUID, replacement: UUID) -> int:
        """Mark every chunk of a version as superseded. Content is never rewritten."""
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE chunks SET superseded_by = ? WHERE document_version_id = ?",
                (str(replacement), str(version_id)),
            )
            changed = int(cursor.rowcount)
        if changed:
            self._append_journal(
                {
                    "op": "supersede",
                    "document_version_id": str(version_id),
                    "superseded_by": str(replacement),
                }
            )
        return changed

    def record_audit(self, event: str, payload: dict[str, object]) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO audit (recorded, event, payload) VALUES (?,?,?)",
                (datetime.now(UTC).isoformat(), event, json.dumps(payload, ensure_ascii=False)),
            )

    # ------------------------------------------------------------------- reading

    def spans(self) -> Iterator[EvidenceSpan]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM chunks").fetchall()
        for row in rows:
            yield _row_to_span(row)

    def count(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
        return int(row["n"])

    def audit_count(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS n FROM audit").fetchone()
        return int(row["n"])

    def audit_for(self, trace_id: str, limit: int = 200) -> list[dict[str, object]]:
        """Every recorded event that carries this trace id, oldest first.

        The auditor's question is "why was this shown", and it is answered from the
        trail rather than by re-running the pipeline against a corpus that has since
        changed.
        """
        with self._lock:
            rows = self._connection.execute(
                "SELECT recorded, event, payload FROM audit "
                "WHERE payload LIKE ? ORDER BY id ASC LIMIT ?",
                (f'%"trace_id": "{trace_id}"%', limit),
            ).fetchall()
        events: list[dict[str, object]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                payload = {"unreadable": True}
            events.append(
                {"recorded": row["recorded"], "event": row["event"], "payload": payload}
            )
        return events

    def healthy(self) -> bool:
        try:
            self._verify_integrity()
        except sqlite3.DatabaseError:
            return False
        return True

    # ------------------------------------------------------------------ recovery

    def replay_journal(self) -> int:
        """Rebuild the chunk table from the append-only journal. Returns rows restored."""
        if not self.journal.exists():
            return 0
        restored = 0
        for line in self.journal.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                log.error("skipping unreadable journal line: %s", error)
                continue
            # Operations are replayed in the order they were accepted, so a chunk that
            # was ingested, approved and later superseded comes back in that state.
            operation = record.pop("op", "add")
            try:
                if operation == "review":
                    self._replay_review(record)
                elif operation == "supersede":
                    self._replay_supersede(record)
                else:
                    restored += self._replay_add(record)
            except (KeyError, ValueError) as error:
                log.error("skipping unreplayable journal line (%s): %s", operation, error)
                continue
        log.info("restored %d chunks from journal", restored)
        return restored

    def _replay_add(self, record: dict[str, object]) -> int:
        content_sha256 = str(record.pop("content_sha256", ""))
        ingested_at = record.pop("ingested_at", None)
        span = EvidenceSpan.model_validate(record)
        moment = (
            datetime.fromisoformat(str(ingested_at)) if ingested_at else datetime.now(UTC)
        )
        try:
            with self._lock:
                self._connection.execute(
                    "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    _span_to_row(span, content_sha256, moment),
                )
        except sqlite3.IntegrityError:
            return 0
        return 1

    def _replay_review(self, record: dict[str, object]) -> None:
        tier = record.get("access_tier")
        with self._lock:
            if tier is None:
                self._connection.execute(
                    "UPDATE chunks SET review_state = ? WHERE document_version_id = ?",
                    (str(record["review_state"]), str(record["document_version_id"])),
                )
            else:
                self._connection.execute(
                    "UPDATE chunks SET review_state = ?, access_tier = ? "
                    "WHERE document_version_id = ?",
                    (
                        str(record["review_state"]),
                        str(tier),
                        str(record["document_version_id"]),
                    ),
                )

    def _replay_supersede(self, record: dict[str, object]) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE chunks SET superseded_by = ? WHERE document_version_id = ?",
                (str(record["superseded_by"]), str(record["document_version_id"])),
            )
