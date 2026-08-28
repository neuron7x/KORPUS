"""Negative controls for the two admission surfaces that had none.

`completed_response_text` is the only thing standing between a raw external
envelope and the answer path, and `validate_partitions` is the only thing
standing between a tuning run and train/validation leakage. Both were written
fail-closed and both were measured at 0% branch coverage on their refusal
paths: every existing test drove the accepting branch, so a rewrite that
returned the text of a *failed* response, or accepted overlapping partitions,
would have passed the suite unchanged.
"""

from __future__ import annotations

import pytest
from korpus.application.ranking_evaluation import JudgedCandidate, JudgedQuery
from korpus.application.tuning_validation import validate_partitions
from korpus.infrastructure.openai_response import completed_response_text


def _query(query_id: str) -> JudgedQuery:
    return JudgedQuery(
        query_id=query_id,
        query=query_id,
        candidates=(JudgedCandidate(text=f"{query_id} evidence", relevance=1),),
    )


def test_only_a_completed_error_free_object_yields_text() -> None:
    """Status and error are checked together: either one alone admits a failed run."""
    completed = {"status": "completed", "error": None, "output_text": " answer "}
    assert completed_response_text(completed) == "answer"

    assert completed_response_text({**completed, "status": "incomplete"}) == ""
    assert completed_response_text({**completed, "status": "failed"}) == ""
    assert completed_response_text({**completed, "error": {"code": "rate_limit"}}) == ""


def test_a_non_object_envelope_is_refused_rather_than_coerced() -> None:
    """A transport that returns a string, a list or nothing is a protocol failure."""
    for body in ("completed", ["completed"], None, 0):
        assert completed_response_text(body) == ""


def test_output_must_be_a_list_to_be_walked() -> None:
    """`output` typed as anything else is refused, not iterated character by character."""
    base = {"status": "completed", "error": None}
    assert completed_response_text({**base, "output": "text"}) == ""
    assert completed_response_text({**base, "output": {"content": []}}) == ""
    assert completed_response_text({**base, "output": []}) == ""


def test_only_text_typed_blocks_contribute() -> None:
    """A refusal, a tool call or an unknown block type contributes nothing."""
    body = {
        "status": "completed",
        "error": None,
        "output": [
            {
                "content": [
                    {"type": "refusal", "refusal": "no"},
                    {"type": "output_text", "text": "kept"},
                    {"type": "output_text", "text": 42},
                    "not-a-block",
                ]
            },
            {"content": "not-a-list"},
            "not-an-item",
        ],
    }
    assert completed_response_text(body) == "kept"


def test_duplicate_query_ids_inside_one_partition_are_rejected() -> None:
    """Two rows with one id make the same query count twice in its own metric."""
    training = (_query("a"), _query("a"))
    validation = (_query("c"), _query("d"))
    with pytest.raises(ValueError, match="unique"):
        validate_partitions(training, validation)

    with pytest.raises(ValueError, match="unique"):
        validate_partitions((_query("a"), _query("b")), (_query("c"), _query("c")))


def test_partitions_that_share_a_query_id_are_rejected() -> None:
    """A held-out set that overlaps training is not held out; the metric reads as skill."""
    with pytest.raises(ValueError, match="disjoint"):
        validate_partitions((_query("a"), _query("b")), (_query("b"), _query("c")))

    validate_partitions((_query("a"), _query("b")), (_query("c"), _query("d")))
