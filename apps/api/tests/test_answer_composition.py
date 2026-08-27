"""An agent may arrange the evidence and open with one line. It may not add a fact.

The extractive answer is correct and reads badly: four sentences from four manuals, in
retrieval order, starting mid-page. A soldier asking «як накласти турнікет» gets the right
passages in the wrong shape, and the shape decides whether they are read.

So a model composes, and what it may compose is bounded by something checkable rather
than by a prompt. Every test here is an attempt to get a fact past that boundary, because
a prompt is a request and `admissible_opening` is the answer.

Numbers and negation have their own rules, and they are the reason this file exists.
"не менше 30 м" and "не менше 300 м" differ by one character; "дозволяється" and
"не дозволяється" by one word. A gate that only checked that every token appeared
somewhere in the evidence would pass both, because "не" appears in almost every Ukrainian
document and "300" appears in plenty.
"""

from __future__ import annotations

import time

import pytest
from korpus.application.composition import (
    MAX_OPENING_WORDS,
    CompositionRefused,
    admissible_opening,
    compose_answer,
)

SPANS = [
    "Джгут накладається вище рани на п'ять сантиметрів.",
    "Час накладання записується на пов'язці пораненого.",
]


class _Composer:
    def __init__(self, opening: str, sentences: list[str] | None = None) -> None:
        self.opening = opening
        self.sentences = sentences

    def compose(self, question: str, sentences: list[str]) -> tuple[str, list[str]]:
        return self.opening, self.sentences if self.sentences is not None else []


def _compose(opening: str, sentences: list[str] | None = None):
    return compose_answer("як накласти джгут", SPANS, _Composer(opening, sentences))


def test_an_opening_made_of_words_in_the_evidence_is_admitted() -> None:
    composition, reason = _compose("Джгут накладається вище рани, час записується")

    assert composition is not None, reason
    assert composition.sentences == tuple(SPANS)


def test_an_opening_that_states_something_the_evidence_does_not_is_refused() -> None:
    """The whole point. A word nobody can check against a quote is a claim."""
    composition, reason = _compose("Джгут накладається на стегнову артерію")

    assert composition is None
    assert "evidence does not" in reason, reason


def test_an_opening_that_states_a_number_is_refused() -> None:
    """Every figure a reader acts on must come from a sentence carrying a hash."""
    composition, reason = _compose("Джгут накладається вище рани на 50 сантиметрів")

    assert composition is None
    assert "number" in reason, reason


@pytest.mark.parametrize("negation", ["не", "без", "заборонено"])
def test_an_opening_that_introduces_a_negation_is_refused(negation: str) -> None:
    """One word flips a norm without changing its vocabulary."""
    composition, reason = _compose(f"Джгут {negation} накладається вище рани")

    assert composition is None
    assert "negation" in reason, reason


def test_dropping_a_retrieved_sentence_is_refused() -> None:
    """A composer that drops evidence decides what the reader does not see."""
    composition, reason = _compose("Джгут накладається вище рани", SPANS[:1])

    assert composition is None
    assert "permutation" in reason, reason


def test_adding_a_sentence_nobody_retrieved_is_refused() -> None:
    composition, reason = _compose(
        "Джгут накладається вище рани", [*SPANS, "Джгут знімається через дві години."]
    )

    assert composition is None
    assert "permutation" in reason, reason


def test_reordering_is_allowed_because_it_invents_nothing() -> None:
    composition, reason = _compose("Джгут накладається вище рани", list(reversed(SPANS)))

    assert composition is not None, reason
    assert composition.sentences == tuple(reversed(SPANS))


def test_a_composer_that_fails_leaves_the_extract_untouched() -> None:
    class _Broken:
        def compose(self, question: str, sentences: list[str]) -> tuple[str, list[str]]:
            raise TimeoutError("provider did not answer")

    composition, reason = compose_answer("питання", SPANS, _Broken())

    assert composition is None
    assert "composer unavailable" in reason


def test_a_blocked_composer_cannot_hold_the_answer_path_past_its_deadline() -> None:
    class _Blocked:
        def compose(self, question: str, sentences: list[str]) -> tuple[str, list[str]]:
            time.sleep(0.4)
            return "late", sentences

    started = time.monotonic()
    composition, reason = compose_answer("питання", SPANS, _Blocked(), deadline_seconds=0.01)

    assert time.monotonic() - started < 0.2
    assert composition is None
    assert "composer exceeded 0.01s deadline" in reason


def test_no_composer_is_the_same_as_a_composer_that_says_nothing() -> None:
    assert compose_answer("питання", SPANS, None)[0] is None


def test_an_opening_longer_than_a_line_is_refused() -> None:
    """A framing line cannot smuggle a claim past a reader who is skimming."""
    words = " ".join(["джгут"] * (MAX_OPENING_WORDS + 1))

    with pytest.raises(CompositionRefused, match="words"):
        admissible_opening(words, "\n".join(SPANS))


def test_the_gate_checks_against_what_the_reader_is_shown() -> None:
    """A line justified by a passage nobody was shown is a line nobody can check."""
    with pytest.raises(CompositionRefused, match="evidence does not"):
        admissible_opening("Джгут накладається на плече", SPANS[1])
