"""A migration that answers from a mixed index is worse than one that has not started.

RAG-016 asks for "durable pipeline для backfill, stale vectors, dual-index migration й
rollback", with an acceptance predicate of "100% approved spans have correct model/text
hash before semantic weight activation".

The failure being prevented is not slowness. Retrieval filters vectors by model id, so
during a re-embed the index holds two populations and the active model covers some
moving subset of the corpus. Answers drawn from that subset come from a candidate set
the calibrated profile never described, and nothing in the response says so — retrieval
reports no error when a filter matches nothing.

So every test here is about ordering and refusal: what may not happen before what.
"""

from __future__ import annotations

import pytest
from korpus.application.embedding_migration import (
    BUILD,
    RETIRE,
    SWITCH,
    plan_migration,
    resume_from,
    retire_admissible,
    rollback_available,
    switch_admissible,
)


def _plan(**overrides):
    values = dict(from_model="embed-v1", to_model="embed-v2", dimensions=768, spans_total=1200)
    values.update(overrides)
    return plan_migration(**values)


def test_a_migration_is_planned_as_resumable_batches() -> None:
    """The dual, and the reason batching is not an optimisation: a migration that
    cannot resume must restart from zero after any interruption, which at corpus scale
    means it does not finish."""
    plan = _plan(batch_size=500)

    assert plan.valid
    assert [b.span_count for b in plan.batches] == [500, 500, 200]
    assert plan.batches[-1].first_span == 1000


def test_the_stages_never_retire_before_switching() -> None:
    """Retiring first leaves no complete population under any model — the mixed state
    the whole plan exists to avoid, entered deliberately."""
    plan = _plan()

    assert plan.stages == (BUILD, SWITCH, RETIRE)
    assert plan.stages.index(SWITCH) < plan.stages.index(RETIRE)


def test_migrating_a_model_to_itself_is_refused() -> None:
    """It is a backfill. Run as a migration, the retire stage deletes what it built."""
    plan = _plan(to_model="embed-v1")

    assert not plan.valid
    assert any("backfill, not a migration" in problem for problem in plan.problems)


@pytest.mark.parametrize(
    "overrides",
    [{"dimensions": 4}, {"batch_size": 0}, {"from_model": ""}, {"spans_total": -1}],
)
def test_a_plan_that_cannot_be_executed_is_refused(overrides: dict) -> None:
    assert not _plan(**overrides).valid


def test_an_empty_corpus_produces_no_batches_but_is_not_an_error() -> None:
    plan = _plan(spans_total=0)

    assert plan.valid
    assert plan.batches == ()


def test_the_switch_requires_complete_coverage() -> None:
    """The acceptance predicate, stated as a refusal."""
    allowed, reason = switch_admissible(
        spans_total=1200, spans_embedded_target=1199, spans_stale_text=0
    )

    assert allowed is False
    assert "1 of 1200" in reason


def test_the_switch_requires_no_stale_vectors() -> None:
    """A vector computed from text that changed would become the authoritative match."""
    allowed, reason = switch_admissible(
        spans_total=1200, spans_embedded_target=1200, spans_stale_text=3
    )

    assert allowed is False
    assert "since changed" in reason


def test_the_switch_is_allowed_at_complete_coverage() -> None:
    allowed, _ = switch_admissible(spans_total=1200, spans_embedded_target=1200, spans_stale_text=0)

    assert allowed is True


def test_an_empty_index_is_not_complete_coverage() -> None:
    """0/0 is arithmetically complete and operationally meaningless."""
    allowed, _ = switch_admissible(spans_total=0, spans_embedded_target=0, spans_stale_text=0)

    assert allowed is False


def test_retiring_before_the_switch_is_refused() -> None:
    """The old population is the only thing that can answer while the new one is
    incomplete; deleting it first destroys the rollback path."""
    allowed, reason = retire_admissible(
        switched=False, spans_embedded_target=1200, spans_total=1200
    )

    assert allowed is False
    assert "only complete population" in reason


def test_retiring_after_a_coverage_regression_is_refused() -> None:
    """Spans added after the switch are not covered by the new model either."""
    allowed, reason = retire_admissible(switched=True, spans_embedded_target=1200, spans_total=1300)

    assert allowed is False
    assert "regressed" in reason


def test_retiring_is_allowed_once_the_switch_holds() -> None:
    allowed, _ = retire_admissible(switched=True, spans_embedded_target=1200, spans_total=1200)

    assert allowed is True


def test_rollback_is_checked_before_it_is_needed() -> None:
    """The question a rollback plan must answer in advance, not during an incident."""
    assert rollback_available(spans_embedded_source=1200, spans_total=1200)[0] is True

    available, reason = rollback_available(spans_embedded_source=900, spans_total=1200)
    assert available is False
    assert "900 of 1200" in reason


def test_resume_returns_the_first_gap_not_the_next_index() -> None:
    """Completing 0, 1, 3 and resuming at 4 leaves batch 2 unembedded, and the coverage
    check then refuses the switch — correctly, after the whole corpus was processed."""
    plan = _plan(batch_size=300)

    assert resume_from([0, 1, 3], plan).index == 2


def test_resume_returns_nothing_when_every_batch_is_done() -> None:
    plan = _plan(batch_size=600)

    assert resume_from([0, 1], plan) is None


def test_the_plan_says_what_executing_it_would_not_prove() -> None:
    rendered = _plan().as_dict()

    assert "external evidence" in str(rendered["interpretation"])
    assert rendered["stages"] == [BUILD, SWITCH, RETIRE]
