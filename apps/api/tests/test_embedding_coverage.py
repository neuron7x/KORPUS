"""An incomplete semantic index does not answer worse — it stops answering.

Retrieval filters `span_embeddings` by the active model id, so a model change produces
zero semantic candidates rather than wrong ones. The lexical half of the hybrid then
answers alone, from a narrower candidate set than the calibrated profile assumed, and
nothing in the response says so.

The four states are distinguished because the operator's next move differs: backfill
embeds what is missing, migration re-embeds what exists under a superseded model. The
stale case is ordered first among the failures deliberately — a missing vector produces
silence, a stale one produces a confident match against text the document no longer
contains.
"""

from __future__ import annotations

import pytest
from korpus.application.embedding_coverage import (
    BACKFILL_REQUIRED,
    COMPLETE,
    MODEL_MIGRATION_REQUIRED,
    NO_CORPUS,
    STALE_VECTORS,
    assess_embedding_coverage,
    semantic_retrieval_admissible,
)


def _coverage(**overrides: object):
    values: dict[str, object] = {
        "active_model_id": "embed-v2",
        "active_dimensions": 768,
        "spans_total": 100,
        "spans_embedded_active": 100,
        "spans_embedded_other_model": 0,
        "spans_stale_text": 0,
    }
    values.update(overrides)
    return assess_embedding_coverage(**values)  # type: ignore[arg-type]


def test_a_fully_embedded_corpus_is_complete() -> None:
    """The dual: without it every failing state below could be the only reachable one."""
    coverage = _coverage()

    assert coverage.status == COMPLETE
    assert coverage.coverage_ratio == 1.0
    assert coverage.complete is True


def test_missing_vectors_call_for_a_backfill() -> None:
    coverage = _coverage(spans_embedded_active=60)

    assert coverage.status == BACKFILL_REQUIRED
    assert "40 spans have no vector" in coverage.reasons[0]
    assert coverage.coverage_ratio == pytest.approx(0.6)


def test_vectors_under_a_superseded_model_call_for_a_migration() -> None:
    """Backfill and migration are different jobs, and the wrong one is expensive."""
    coverage = _coverage(spans_embedded_active=0, spans_embedded_other_model=100)

    assert coverage.status == MODEL_MIGRATION_REQUIRED
    assert "other than 'embed-v2'" in coverage.reasons[0]


def test_a_stale_vector_outranks_a_missing_one() -> None:
    """Missing produces silence; stale produces confidence about absent text."""
    coverage = _coverage(spans_embedded_active=90, spans_stale_text=3)

    assert coverage.status == STALE_VECTORS
    assert "since changed" in coverage.reasons[0]


def test_an_empty_corpus_covers_nothing_rather_than_everything() -> None:
    """0/0 = 1.0 is the arithmetic that lets a fresh deployment pass a coverage gate."""
    coverage = _coverage(spans_total=0, spans_embedded_active=0)

    assert coverage.status == NO_CORPUS
    assert coverage.coverage_ratio == 0.0
    assert coverage.complete is False


def test_required_semantic_mode_refuses_an_incomplete_index() -> None:
    """The policy says required semantic mode never silently falls back."""
    allowed, reason = semantic_retrieval_admissible(_coverage(spans_embedded_active=99))

    assert allowed is False
    assert BACKFILL_REQUIRED in reason


def test_required_semantic_mode_serves_a_complete_index() -> None:
    allowed, reason = semantic_retrieval_admissible(_coverage())

    assert allowed is True
    assert "every span is retrievable" in reason


def test_required_semantic_mode_refuses_an_empty_index() -> None:
    """A deployment with no corpus must not read as ready to serve semantically."""
    allowed, _ = semantic_retrieval_admissible(_coverage(spans_total=0, spans_embedded_active=0))

    assert allowed is False


def test_the_report_names_the_model_it_measured_against() -> None:
    """A coverage figure without the model it applies to is not a measurement."""
    rendered = _coverage(spans_embedded_active=50).as_dict()

    assert rendered["active_model_id"] == "embed-v2"
    assert rendered["active_dimensions"] == 768
    assert rendered["coverage_ratio"] == 0.5
    assert "returns none" in str(rendered["interpretation"])
