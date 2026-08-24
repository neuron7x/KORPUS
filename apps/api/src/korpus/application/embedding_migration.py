"""Moving a semantic index from one model to another without answering from a mixed one.

RAG-016: "Є upsert/search, але немає доведеного durable pipeline для backfill, stale
vectors, dual-index migration й rollback." `embedding_coverage.py` says which of four
states an index is in; this says what to do about it, and — the part that matters —
what must not happen while it is being done.

The failure this prevents is not a slow migration. It is a *mixed* one. Retrieval
filters vectors by model id, so during a re-embed the index holds two populations and
the active model covers a shrinking or growing subset of the corpus. Every answer drawn
from that subset is drawn from a candidate set the calibrated profile never described,
and nothing in the response says so. The finding's acceptance predicate is exactly
this: "100% approved spans have correct model/text hash before semantic weight
activation."

So the plan is blue-green by construction. The new model's vectors are built while the
old model stays active; the switch happens only when coverage under the new model is
complete; and rollback is the same operation in reverse, which is possible only because
the old vectors were never deleted during the build.

Batching is not an optimisation here. A migration that cannot resume is one that must
be restarted from zero after any interruption, which at corpus scale means it does not
finish — so the plan is a sequence of batches with a cursor, and the ledger records
which batch produced which vectors.

What this module does not do is embed anything. It computes and validates the plan; the
worker that executes it runs against a real index and real embedding service, and the
evidence that it works on the operational corpus stays external — that is the half of
RAG-016 that no code in this tree can close.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from korpus.application.embedding_contracts import counters_within_total

BUILD = "BUILD"
SWITCH = "SWITCH"
RETIRE = "RETIRE"
ROLLBACK = "ROLLBACK"

#: Spans per batch. A batch that fails is retried whole, so the size trades restart cost
#: against how much progress a single failure discards.
DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True)
class MigrationBatch:
    index: int
    first_span: int
    span_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "first_span": self.first_span,
            "span_count": self.span_count,
        }


@dataclass(frozen=True)
class MigrationPlan:
    from_model: str
    to_model: str
    dimensions: int
    spans_total: int
    batches: tuple[MigrationBatch, ...]
    problems: tuple[str, ...] = field(default_factory=tuple)

    @property
    def valid(self) -> bool:
        return not self.problems

    @property
    def stages(self) -> tuple[str, ...]:
        """BUILD then SWITCH then RETIRE. Never RETIRE before SWITCH.

        Retiring the old vectors first would leave the corpus with no complete
        population under any model — the mixed-index state the migration exists to
        avoid, entered deliberately.
        """
        return (BUILD, SWITCH, RETIRE)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "valid": self.valid,
            "from_model": self.from_model,
            "to_model": self.to_model,
            "dimensions": self.dimensions,
            "spans_total": self.spans_total,
            "batches": [batch.as_dict() for batch in self.batches],
            "stages": list(self.stages),
            "problems": list(self.problems),
            "interpretation": (
                "Blue-green: vectors for the new model are built while the old model "
                "keeps serving, the switch happens only at complete coverage, and the "
                "old vectors are retired last so rollback stays available. Executing "
                "this against a real index and embedding service is external evidence."
            ),
        }


def plan_migration(
    *,
    from_model: str,
    to_model: str,
    dimensions: int,
    spans_total: int,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> MigrationPlan:
    """Compute the batch sequence, refusing plans that cannot be executed safely."""

    problems: list[str] = []
    if not from_model or not to_model:
        problems.append("both the current and the target model must be named")
    if from_model == to_model:
        problems.append(
            "the target model is the active model: this is a backfill, not a migration, "
            "and running it as one would retire the vectors it just built"
        )
    if dimensions < 8:
        problems.append(f"dimensions must be at least 8, got {dimensions}")
    if batch_size < 1:
        problems.append("batch size must be positive")
    if spans_total < 0:
        problems.append("span count cannot be negative")

    batches: list[MigrationBatch] = []
    if not problems and spans_total:
        for index, first in enumerate(range(0, spans_total, batch_size)):
            batches.append(
                MigrationBatch(
                    index=index,
                    first_span=first,
                    span_count=min(batch_size, spans_total - first),
                )
            )
    return MigrationPlan(
        from_model=from_model,
        to_model=to_model,
        dimensions=dimensions,
        spans_total=spans_total,
        batches=tuple(batches),
        problems=tuple(problems),
    )


def switch_admissible(
    *, spans_total: int, spans_embedded_target: int, spans_stale_text: int
) -> tuple[bool, str]:
    """Whether the new model may become the active one.

    Complete coverage, and no vector computed from text that has since changed. Anything
    less means the switch creates the mixed index the migration exists to avoid — and it
    would do so silently, because retrieval reports no error when a filter matches
    nothing.
    """
    if not counters_within_total(spans_total, spans_embedded_target, spans_stale_text):
        return False, "coverage counters are inconsistent with total spans"
    if spans_total == 0:
        return False, "no spans exist, so coverage under the target model is not evidence"
    if spans_stale_text:
        return False, (
            f"{spans_stale_text} spans carry a vector computed from text that has since "
            "changed; switching would make those the authoritative match"
        )
    if spans_embedded_target < spans_total:
        missing = spans_total - spans_embedded_target
        return False, (
            f"{missing} of {spans_total} spans have no vector under the target model; "
            "the acceptance predicate is 100% before semantic weight activation"
        )
    return True, "every span is retrievable under the target model"


def retire_admissible(
    *, switched: bool, spans_embedded_target: int, spans_total: int
) -> tuple[bool, str]:
    """Whether the superseded vectors may be deleted.

    Only after the switch, and only at complete coverage. Retiring earlier destroys the
    rollback path: the old population is the only thing that can answer while the new
    one is incomplete.
    """
    if not switched:
        return False, (
            "the switch has not happened; the old vectors are the only complete population"
        )
    admissible, reason = switch_admissible(
        spans_total=spans_total,
        spans_embedded_target=spans_embedded_target,
        spans_stale_text=0,
    )
    if not admissible:
        return False, f"coverage regressed after the switch: {reason}"
    return True, "the target model covers every span and the switch is in effect"


def rollback_available(*, spans_embedded_source: int, spans_total: int) -> tuple[bool, str]:
    """Whether the previous model can still serve.

    The question a rollback plan has to answer before it is needed, not after.
    """
    if not counters_within_total(spans_total, spans_embedded_source):
        return False, "rollback coverage counters are inconsistent"
    if spans_total and spans_embedded_source == spans_total:
        return True, "the previous model still covers every span"
    return False, (
        f"the previous model covers {spans_embedded_source} of {spans_total} spans; "
        "rollback would serve from an incomplete index"
    )


def resume_from(completed: Sequence[int], plan: MigrationPlan) -> MigrationBatch | None:
    """The first batch not yet completed, so an interrupted migration continues.

    Gaps matter: completing batches 0, 1 and 3 and resuming at 4 would leave batch 2
    unembedded and the coverage check would then refuse the switch — correctly, and
    after the whole corpus had been processed. The first gap is the resume point.
    """
    done = set(completed)
    for batch in plan.batches:
        if batch.index not in done:
            return batch
    return None
