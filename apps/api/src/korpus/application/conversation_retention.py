"""How long a soldier's questions are kept, and what happens when nobody has decided.

The corpus has a retention policy. Conversations did not: `conversations` and `messages`
grew without bound and appeared in no disposition plan. Two separate problems wear that one
shape.

  operational   a table nothing ever deletes is a table that is fine until the day it is
                not, and the day it is not is chosen by the disk rather than by anyone.

  what is in it A question is not neutral text. "як накласти турнікет" says somebody was
                bleeding; a sequence of them says where a unit was and what it was doing.
                Held for ever, that is an intelligence product about our own people, sitting
                in the same database as the manuals.

The policy is *computed* here and applied nowhere. `scripts/conversation_retention.py`
prints the plan; deletion needs an operator to pass `--apply`. That split is the same one
`retention_policy.py` already makes, and for the same reason: a job that silently deletes a
soldier's history the first time it runs is worse than no job.

The state that matters most is the undeclared one. With no window configured this reports
`NOT_DECLARED` — not `PASS`, not "keep for ever". Nobody has decided how long these are
kept, and a report that renders that as green is how the decision never gets made.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

#: Below this, a policy would delete a shift's history while the shift is still running.
#: Refused rather than clamped: a number somebody typed by mistake should fail loudly.
MINIMUM_RETENTION_DAYS = 7

#: Above this the window is indistinguishable from keeping for ever, which is the state
#: this module exists to stop being the unexamined default.
MAXIMUM_RETENTION_DAYS = 3650


class Disposition(StrEnum):
    KEEP = "keep"
    EXPIRED = "expired"


class RetentionState(StrEnum):
    NOT_DECLARED = "not_declared"
    DECLARED = "declared"


class InvalidRetentionWindow(ValueError):
    """A window nobody could have meant. Raised at configuration time, not at deletion."""


@dataclass(frozen=True)
class Decision:
    conversation_id: UUID
    disposition: Disposition
    age_days: int
    reason: str


@dataclass(frozen=True)
class RetentionPlan:
    """What would be deleted, if anybody asked for it to be.

    `state` is separate from the list because an empty list means two different things: no
    conversation is old enough, or no window is declared and nothing can be old enough. A
    report that could not tell those apart would read as compliant in the second case.
    """

    state: RetentionState
    window_days: int | None
    evaluated_at: datetime
    decisions: tuple[Decision, ...]

    @property
    def expired(self) -> tuple[Decision, ...]:
        return tuple(item for item in self.decisions if item.disposition is Disposition.EXPIRED)

    @property
    def status(self) -> str:
        if self.state is RetentionState.NOT_DECLARED:
            # Not a failure of the code. A failure to have decided, reported as itself.
            return "NOT_DECLARED"
        return "PLANNED" if self.expired else "NOTHING_DUE"

    def as_report(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": self.status,
            "state": self.state.value,
            "window_days": self.window_days,
            "evaluated_at": self.evaluated_at.isoformat(),
            "conversations": len(self.decisions),
            "expired": [
                {
                    "conversation_id": str(item.conversation_id),
                    "age_days": item.age_days,
                    "reason": item.reason,
                }
                for item in self.expired
            ],
            "interpretation": (
                "A plan, not an action: nothing is deleted without an operator passing "
                "--apply. With no window declared the status is NOT_DECLARED rather than "
                "PASS — a question a soldier asked is kept for ever by default, and a "
                "report that renders that as green is how nobody ever decides otherwise."
            ),
        }


def validate_window(days: int) -> int:
    if days < MINIMUM_RETENTION_DAYS:
        raise InvalidRetentionWindow(
            f"a retention window of {days} days would delete a shift's history while the "
            f"shift is still running; the minimum is {MINIMUM_RETENTION_DAYS}"
        )
    if days > MAXIMUM_RETENTION_DAYS:
        raise InvalidRetentionWindow(
            f"a window of {days} days is indistinguishable from keeping for ever; the "
            f"maximum is {MAXIMUM_RETENTION_DAYS}"
        )
    return days


def plan_retention(
    conversations: list[tuple[UUID, datetime]],
    *,
    window_days: int | None,
    now: datetime | None = None,
) -> RetentionPlan:
    """Dispositions for `(id, last_activity)` pairs. Deletes nothing.

    Age is measured from the last activity, not from creation: a conversation somebody
    returned to yesterday is current however old its first question is, and deleting it
    because the shift started a month ago would take away exactly the history that is being
    used.
    """
    moment = now or datetime.now(UTC)
    if window_days is None:
        return RetentionPlan(RetentionState.NOT_DECLARED, None, moment, ())

    window = validate_window(window_days)
    cutoff = moment - timedelta(days=window)
    decisions = []
    for conversation_id, last_activity in conversations:
        aware = last_activity if last_activity.tzinfo else last_activity.replace(tzinfo=UTC)
        age = max(0, (moment - aware).days)
        expired = aware < cutoff
        decisions.append(
            Decision(
                conversation_id=conversation_id,
                disposition=Disposition.EXPIRED if expired else Disposition.KEEP,
                age_days=age,
                reason=(
                    f"no activity for {age} days, beyond the declared {window}"
                    if expired
                    else f"last activity {age} days ago, within the declared {window}"
                ),
            )
        )
    return RetentionPlan(RetentionState.DECLARED, window, moment, tuple(decisions))
