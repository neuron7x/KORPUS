"""What may be deleted, what must be kept, and what nobody has decided.

`CorpusPolicy` carries `retention_days`, `legal_hold` and an `allowed_operations` set
that may or may not include DELETE. Nothing computed anything from them:
`TECHNICAL_DEBT_V5.md` lists an "executable retention/deletion/legal-hold scheduler and
reconciliation" as open, and until now the retention period was a number in a profile
that no code had ever compared to a date.

This module computes a plan and deletes nothing. That is not caution for its own sake:
in a corpus that answers "which order was in force on date X", deleting a superseded
version destroys the ability to answer for past dates, and doing it automatically on a
timer would be a data-loss mechanism driven by a config field. The plan is the
artefact an owner reviews; deletion is a separate, authorised act against a plan whose
digest they saw.

Four dispositions, and the distinctions between them are the point:

    HELD               — legal hold. Never eligible, whatever the age.
    RETAINED           — inside the retention period.
    ELIGIBLE           — past the period, and the corpus policy permits DELETE.
    AWAITING_DECISION  — past the period, and it does not. The system must not delete,
                         and must not pretend the material has been dealt with.

The last one exists because the alternative shapes are both wrong. Silently keeping it
forever reports a clean retention posture over material nobody has decided about;
deleting it because the timer expired ignores that the owner never granted DELETE.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from korpus.security.corpus_governance import CorpusOperation, CorpusPolicy

HELD = "HELD"
RETAINED = "RETAINED"
ELIGIBLE = "ELIGIBLE"
AWAITING_DECISION = "AWAITING_DECISION"
UNGOVERNED = "UNGOVERNED"


@dataclass(frozen=True)
class RetentionItem:
    document_id: str
    corpus_id: str
    created_at: datetime
    disposition: str
    reason: str
    retention_expires_at: datetime | None


@dataclass(frozen=True)
class RetentionPlan:
    evaluated_at: datetime
    items: tuple[RetentionItem, ...]

    def by_disposition(self, disposition: str) -> tuple[RetentionItem, ...]:
        return tuple(item for item in self.items if item.disposition == disposition)

    @property
    def deletable_ids(self) -> tuple[str, ...]:
        return tuple(item.document_id for item in self.by_disposition(ELIGIBLE))

    def as_dict(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.disposition] = counts.get(item.disposition, 0) + 1
        return {
            "schema_version": 1,
            "evaluated_at": self.evaluated_at.isoformat(),
            "counts": counts,
            "items": [
                {
                    "document_id": item.document_id,
                    "corpus_id": item.corpus_id,
                    "created_at": item.created_at.isoformat(),
                    "disposition": item.disposition,
                    "reason": item.reason,
                    "retention_expires_at": (
                        item.retention_expires_at.isoformat()
                        if item.retention_expires_at
                        else None
                    ),
                }
                for item in self.items
            ],
            "interpretation": (
                "A plan, not an action. ELIGIBLE means the corpus policy permits "
                "deletion and the retention period has passed; deletion remains a "
                "separate authorised act. AWAITING_DECISION means the period passed "
                "and nobody has granted that permission."
            ),
        }


def _aware(moment: datetime) -> datetime:
    """Naive timestamps come back from SQLite; comparing them to an aware `now` raises."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def plan_retention(
    documents: Iterable[tuple[str, str, datetime]],
    policies: Mapping[str, CorpusPolicy],
    *,
    now: datetime | None = None,
) -> RetentionPlan:
    """Classify each (document id, corpus, creation time) against its corpus policy."""

    evaluated_at = now or datetime.now(UTC)
    items: list[RetentionItem] = []
    for document_id, corpus_id, created_at in documents:
        policy = policies.get(corpus_id)
        if policy is None:
            # An ungoverned corpus is not an empty policy: nothing states who owns the
            # material or how long it may be kept, so no disposition can be computed.
            items.append(
                RetentionItem(
                    document_id=document_id,
                    corpus_id=corpus_id,
                    created_at=_aware(created_at),
                    disposition=UNGOVERNED,
                    reason="corpus has no approved governance policy",
                    retention_expires_at=None,
                )
            )
            continue
        created = _aware(created_at)
        expires_at = created + timedelta(days=policy.retention_days)
        if policy.legal_hold:
            disposition, reason = HELD, "corpus is under legal hold"
        elif evaluated_at < expires_at:
            disposition, reason = RETAINED, "inside the retention period"
        elif CorpusOperation.DELETE in policy.allowed_operations:
            disposition, reason = ELIGIBLE, "retention period elapsed and deletion is permitted"
        else:
            disposition, reason = (
                AWAITING_DECISION,
                "retention period elapsed and the corpus policy does not permit deletion",
            )
        items.append(
            RetentionItem(
                document_id=document_id,
                corpus_id=corpus_id,
                created_at=created,
                disposition=disposition,
                reason=reason,
                retention_expires_at=expires_at,
            )
        )
    return RetentionPlan(evaluated_at=evaluated_at, items=tuple(items))


def reconcile(plan: RetentionPlan, stored_document_ids: Iterable[str]) -> list[str]:
    """Differences between what the plan describes and what the store actually holds.

    Two directions, both of which mean the plan is describing a system that is not
    there: material present in storage that the plan never saw, and material the plan
    expects to protect that has already gone.
    """
    stored = set(stored_document_ids)
    planned = {item.document_id for item in plan.items}
    problems: list[str] = []
    for document_id in sorted(stored - planned):
        problems.append(f"stored document not covered by the retention plan: {document_id}")
    for item in plan.items:
        if item.disposition in {HELD, RETAINED} and item.document_id not in stored:
            problems.append(
                f"document under {item.disposition} is absent from storage: {item.document_id}"
            )
    return problems
