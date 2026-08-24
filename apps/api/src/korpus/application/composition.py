"""An agent may arrange the evidence and open with one line. It may not add a fact.

The extractive answer is correct and reads badly: four sentences lifted from four
different manuals, in retrieval order, starting mid-page. A soldier asking "як накласти
турнікет" gets the right passages in the wrong shape, and the shape is what decides
whether they are read.

So the model composes — and what it is allowed to compose is bounded by something
checkable rather than by a prompt:

  selection and order   it chooses which of the retrieved sentences answer the question,
                        and in what order. That is judgement about evidence, not
                        invention of it.
  one opening line      at most fifteen words, and every content token in it must already
                        appear in the cited spans. No numbers. No negation.

Numbers and negation are excluded by name because they are the two edits that change what
an order says while looking like a paraphrase. "не менше 30 м" and "не менше 300 м" differ
by one character; "дозволяється" and "не дозволяється" by one word. A gate that counted
tokens without these two rules would pass both.

Everything else the reader sees is still a verbatim span with its hash, its page and its
version. A composition that fails admission is dropped and the extract is shown as it was
— the reader loses a nicer opening line and loses nothing else.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from korpus.application.query_plan import PlannerUnavailable

#: A framing line, not a paragraph. Long enough to say what the passages are about,
#: short enough that it cannot smuggle a claim past a reader who is skimming.
MAX_OPENING_WORDS = 15

#: Anything that looks like a quantity. A composition states no numbers at all: every
#: figure a reader acts on must come from a sentence that carries a hash.
_NUMBER = re.compile(r"\d")

#: Negation flips a norm without changing its vocabulary, so it cannot be caught by
#: checking that every token is present in the evidence — "не" is present in almost any
#: Ukrainian document. Refused outright in the opening line.
_NEGATION = frozenset({"не", "ні", "ані", "без", "заборонено", "неможливо", "жоден", "жодного"})

#: Words that carry no fact and therefore need not appear in the evidence.
_FUNCTION_WORDS = frozenset(
    {
        "і",
        "та",
        "й",
        "а",
        "але",
        "або",
        "чи",
        "що",
        "як",
        "це",
        "цей",
        "ця",
        "ці",
        "у",
        "в",
        "з",
        "із",
        "до",
        "від",
        "на",
        "по",
        "за",
        "для",
        "при",
        "про",
        "над",
        "під",
        "між",
        "після",
        "перед",
        "через",
        "щодо",
        "також",
        "крім",
        "того",
        "є",
        "бути",
        "має",
        "мають",
        "слід",
        "треба",
        "може",
        "можна",
        "той",
        "те",
        "ті",
        "його",
        "її",
        "їх",
        "свій",
        "своя",
        "своє",
    }
)

_TOKEN = re.compile(r"[\w'’-]+", re.UNICODE)


class AnswerComposer(Protocol):
    """Arranges retrieved sentences and proposes one opening line.

    Returns `(opening, ordered_sentences)`. An empty opening means "no framing"; an empty
    list means "no opinion about the order", and both are acceptable answers.
    """

    def compose(self, question: str, sentences: list[str]) -> tuple[str, list[str]]: ...


class CompositionRefused(ValueError):
    """Raised with the rule that was broken, never with a generic message."""


@dataclass(frozen=True)
class Composition:
    opening: str
    sentences: tuple[str, ...]

    def as_audit_record(self) -> dict[str, object]:
        return {
            "opening": self.opening,
            "sentence_count": len(self.sentences),
            "interpretation": (
                "The opening line is the system's own words, admitted only because every "
                "content token in it appears in the cited spans and it carries no number "
                "and no negation. Every other sentence is verbatim from a cited span."
            ),
        }


def _normalise(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(_normalise(text))


def admissible_opening(opening: str, evidence: str) -> str:
    """The opening line, or a refusal naming the rule it broke.

    Checked against the evidence the reader will actually see, not against the corpus: a
    line justified by a passage nobody was shown is a line nobody can check.
    """
    text = unicodedata.normalize("NFC", opening).strip()
    if not text:
        raise CompositionRefused("empty opening")
    if len(text.split()) > MAX_OPENING_WORDS:
        raise CompositionRefused(f"opening exceeds {MAX_OPENING_WORDS} words")
    if _NUMBER.search(text):
        raise CompositionRefused(
            "opening states a number; every figure a reader acts on must carry a hash"
        )
    available = set(_tokens(evidence))
    for token in _tokens(text):
        if token in _NEGATION:
            raise CompositionRefused(f"opening introduces a negation: {token!r}")
        if token in _FUNCTION_WORDS or len(token) < 3:
            continue
        if token not in available:
            raise CompositionRefused(f"opening states something the evidence does not: {token!r}")
    return text


def compose_answer(
    question: str,
    sentences: list[str],
    composer: AnswerComposer | None,
) -> tuple[Composition | None, str]:
    """The arranged answer and why, or None and the reason it was refused.

    Every failure ends in the same place — the extract exactly as it was — because that
    is what this system did before a composer existed. A model that is missing, slow,
    broken or hostile costs the reader a better opening line and nothing else.
    """
    if composer is None or not sentences:
        return None, "no composer configured"
    try:
        opening, ordered = composer.compose(question, list(sentences))
    except (PlannerUnavailable, TimeoutError, OSError, ValueError, TypeError) as error:
        # Named rather than blanket, and for the same reason as `build_plan`: everything a
        # provider can do to us arrives as one of these, and anything else is a defect in
        # this tree that must surface rather than be absorbed into "the model had no
        # opinion". The reason travels into the audit chain with the answer.
        return None, f"composer unavailable: {type(error).__name__}: {error}"[:200]

    evidence = "\n".join(sentences)
    try:
        admitted_opening = admissible_opening(opening, evidence)
    except CompositionRefused as refusal:
        return None, f"opening refused: {refusal}"

    # Ordering is a permutation of what was retrieved, checked as one. A composer that
    # dropped a sentence would be deciding what the reader does not see, and a composer
    # that added one would be quoting something nobody retrieved.
    if ordered:
        if sorted(_normalise(item) for item in ordered) != sorted(
            _normalise(item) for item in sentences
        ):
            return None, "ordering is not a permutation of the retrieved sentences"
        arranged = tuple(ordered)
    else:
        arranged = tuple(sentences)

    return Composition(opening=admitted_opening, sentences=arranged), "admitted"
