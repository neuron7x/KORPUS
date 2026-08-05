"""Reading the audit log, apart from writing it.

`SqlRepository` carries forty-eight methods over sixteen hundred lines — COD-001,
"infrastructure god object". Most of it cannot be split without splitting a
transaction: `create_version_bundle` writes rows and their audit event atomically, and
an abstraction that separated them would either break that atomicity or leak it.

These three do not share a transaction with any write. Verification walks the committed
chain, event lookup reads it, readiness reports on it — all `engine.connect()`, none
inside `_transaction_with_anchor`. That is the seam the class actually has, so it is the
one taken; the rest of COD-001 stays open with its measurement recorded rather than
being cut somewhere it does not part.

The canonical form moved with them, because both halves need it: the writer computes
the HMAC over it and the verifier recomputes it. One definition or the chain verifies
against a shape the writer never produced.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, func, select

from korpus.application.trace import TRACE_ID_PATTERN
from korpus.domain.models import AuditVerification, Identity
from korpus.infrastructure.audit_anchor import AnchorError, AuditAnchorStore


def audit_canonical(
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
    """The bytes an audit event is hashed over.

    Module-level rather than a method on either side: the writer and the verifier must
    agree exactly, and two copies of a canonical form is a chain that fails to verify
    against events it produced itself.
    """
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


def iso(value: datetime) -> str:
    """Naive timestamps come back from SQLite; an aware comparison against them raises."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


class AuditReader:
    """Read-side of the audit log: verification, lookup, readiness."""

    def __init__(
        self,
        engine: Engine,
        audit_key: bytes,
        anchor_store: AuditAnchorStore,
        apply_identity: Any,
        audits: Any,
        audit_heads: Any,
        outbox: Any,
        schema_revision: Any,
        expected_schema_revision: str,
    ) -> None:
        self.engine = engine
        self.audit_key = audit_key
        self.anchor_store = anchor_store
        self._apply_identity = apply_identity
        self._audits = audits
        self._audit_heads = audit_heads
        self._outbox = outbox
        # Passed in rather than imported: the expected revision belongs to the migration
        # chain, and a second copy here would drift from it silently — the exact defect
        # SCHEMA_REVISION already caused once, when it stayed at 0009 after 0010 shipped
        # and production would not start.
        self.schema_revision = schema_revision
        self._expected_schema_revision = expected_schema_revision

    def verify_audit(self) -> AuditVerification:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(select(self._audits).order_by(self._audits.c.sequence))
                .mappings()
                .all()
            )
            head_sequence, head_hash = connection.execute(
                select(self._audit_heads.c.sequence, self._audit_heads.c.head_hash).where(
                    self._audit_heads.c.singleton_id == 1
                )
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
            canonical = audit_canonical(
                sequence=row["sequence"],
                event_id=row["event_id"],
                occurred_at=iso(row["occurred_at"]),
                actor_subject=row["actor_subject"],
                action=row["action"],
                resource_type=row["resource_type"],
                resource_id=row["resource_id"],
                payload_json=row["payload_json"],
                previous_hash=row["previous_hash"],
            )
            expected_hash = hmac.new(self.audit_key, canonical, hashlib.sha256).hexdigest()
            if row["previous_hash"] != previous_hash or not hmac.compare_digest(
                expected_hash, row["event_hash"]
            ):
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
        if anchor.sequence > head_sequence:
            # The anchor was written for events the database no longer has: a restore
            # from an older backup, or lost committed rows. This is the failure the
            # anchor exists to catch.
            return AuditVerification(
                valid=False,
                event_count=len(rows),
                head_sequence=head_sequence,
                anchor_valid=False,
                reason="external audit anchor is ahead of the database head",
            )
        anchor_at_position = (
            head_hash
            if anchor.sequence == head_sequence
            else (rows[anchor.sequence - 1]["event_hash"] if anchor.sequence >= 1 else "0" * 64)
        )
        if anchor.head_hash != anchor_at_position:
            return AuditVerification(
                valid=False,
                event_count=len(rows),
                head_sequence=head_sequence,
                anchor_valid=False,
                first_invalid_sequence=anchor.sequence or None,
                reason="external audit anchor mismatch",
            )
        pending = head_sequence - anchor.sequence
        return AuditVerification(
            valid=True,
            event_count=len(rows),
            head_sequence=head_sequence,
            anchor_valid=pending == 0,
            anchor_pending=pending,
            reason=None if pending == 0 else f"{pending} checkpoints awaiting anchor delivery",
        )

    def read_audit_events(
        self, identity: Identity, trace_id: str, *, limit: int = 200
    ) -> list[dict[str, object]]:
        """The events of one request, in order, for an auditor who holds `audit:read`.

        Matching is a substring test against the canonical payload rather than a JSON
        operator, because the payload column is portable text and the canonical form
        (sorted keys, no spaces) makes the encoding of one key exact. The cost is a
        scan; at audit volumes that is acceptable, and it is named here rather than
        hidden. Authorisation is the caller's: this method assumes the permission check
        already happened.
        """
        if not TRACE_ID_PATTERN.fullmatch(trace_id):
            raise ValueError("invalid trace id")
        if limit < 1 or limit > 1000:
            raise ValueError("limit out of range")
        needle = json.dumps({"trace_id": trace_id}, separators=(",", ":"))[1:-1]
        statement = (
            select(
                self._audits.c.sequence,
                self._audits.c.event_id,
                self._audits.c.occurred_at,
                self._audits.c.actor_subject,
                self._audits.c.action,
                self._audits.c.resource_type,
                self._audits.c.resource_id,
                self._audits.c.payload_json,
            )
            .where(self._audits.c.payload_json.contains(needle))
            .order_by(self._audits.c.sequence)
            .limit(limit)
        )
        with self.engine.begin() as connection:
            self._apply_identity(connection, identity)
            rows = connection.execute(statement).mappings().all()
        return [
            {
                "sequence": int(row["sequence"]),
                "event_id": str(row["event_id"]),
                "occurred_at": iso(row["occurred_at"])
                if isinstance(row["occurred_at"], datetime)
                else str(row["occurred_at"]),
                "actor_subject": str(row["actor_subject"]),
                "action": str(row["action"]),
                "resource_type": str(row["resource_type"]),
                "resource_id": None if row["resource_id"] is None else str(row["resource_id"]),
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def readiness_snapshot(
        self, *, max_pending_events: int, max_pending_age_seconds: float
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        with self.engine.connect() as connection:
            database_ok = connection.execute(select(1)).scalar_one() == 1
            head_sequence, head_hash = connection.execute(
                select(self._audit_heads.c.sequence, self._audit_heads.c.head_hash).where(
                    self._audit_heads.c.singleton_id == 1
                )
            ).one()
            pending_count, oldest_pending = connection.execute(
                select(func.count(), func.min(self._outbox.c.created_at)).where(
                    self._outbox.c.delivered_at.is_(None)
                )
            ).one()
        oldest_age = 0.0
        if oldest_pending is not None:
            if oldest_pending.tzinfo is None:
                oldest_pending = oldest_pending.replace(tzinfo=UTC)
            oldest_age = max(0.0, (now - oldest_pending).total_seconds())
        anchor = self.anchor_store.read()
        anchor_not_ahead = anchor.sequence <= head_sequence
        if anchor.sequence == 0:
            anchor_matches_history = anchor.head_hash == "0" * 64
        elif anchor_not_ahead:
            with self.engine.connect() as connection:
                historical_hash = connection.execute(
                    select(self._audits.c.event_hash).where(
                        self._audits.c.sequence == anchor.sequence
                    )
                ).scalar_one_or_none()
            anchor_matches_history = historical_hash is not None and hmac.compare_digest(
                historical_hash, anchor.head_hash
            )
        else:
            anchor_matches_history = False
        anchor_gap = max(0, int(head_sequence) - int(anchor.sequence))
        with self.engine.connect() as connection:
            recoverable_gap = connection.execute(
                select(func.count()).select_from(self._outbox).where(
                    self._outbox.c.sequence > anchor.sequence,
                    self._outbox.c.delivered_at.is_(None),
                )
            ).scalar_one()
        anchor_recoverable = int(recoverable_gap) == anchor_gap
        pending_ok = (
            int(pending_count) <= max_pending_events and oldest_age <= max_pending_age_seconds
        )
        revision = self.schema_revision()
        return {
            "database": database_ok,
            "schema_revision": revision,
            "expected_schema_revision": self._expected_schema_revision,
            "schema_current": revision in {None, self._expected_schema_revision},
            "audit_head_sequence": int(head_sequence),
            "audit_head_hash": head_hash,
            "anchor_sequence": int(anchor.sequence),
            "anchor_not_ahead": anchor_not_ahead,
            "anchor_matches_history": anchor_matches_history,
            "anchor_gap_events": anchor_gap,
            "anchor_gap_recoverable": anchor_recoverable,
            "pending_anchor_events": int(pending_count),
            "oldest_pending_seconds": oldest_age,
            "outbox_within_budget": pending_ok,
            "ready": bool(
                database_ok
                and anchor_not_ahead
                and anchor_matches_history
                and anchor_recoverable
                and pending_ok
            ),
        }