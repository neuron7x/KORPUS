"""Bounded question applicability checks, independent of lexical coverage.

This is a deliberately small grammar, not a natural-language entailment model. It
recognizes explicit names/identifiers and simple Ukrainian/English property lists.
Every recognized obligation is conjunctive; a high overlap cannot cancel a missing
subject or property. Source aliases must occur in the cited text itself.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from korpus.application.answer_adjudication import question_kind
from korpus.application.question_labels import FUNCTION_WORDS as _FUNCTIONS
from korpus.application.question_labels import (
    QUOTED_NAMES as _QUOTED,
)
from korpus.application.question_labels import (
    ambiguous_trailing_label,
    quoted_label_met,
)
from korpus.application.question_labels import (
    normalize_question as _normal,
)
from korpus.application.retrieval_math import tokenize

_WORD = re.compile(r"[^\W_]+(?:['’\-][^\W_]+|\.\d+)*", re.UNICODE)
_PROPERTY = re.compile(r"^(?:який|яка|яке|які|якого|якої|яких|what|which)\s+", re.IGNORECASE)
_VERSION = re.compile(
    r"\b(?:версі[яїю]|редакці[яїю]|version|revision|rev|v)\.?\s+(\d+(?:[.\-]\w+)*)",
    re.IGNORECASE,
)
_CLAUSE = re.compile(r"[;,\n]+|\s+(?:а|але|однак|but|whereas|while)\s+", re.IGNORECASE)
_BINDING = re.compile(r"\s*[—=:]\s*|\s+-\s+|\s+(?:is|are|є|становить|дорівнює)\s+", re.IGNORECASE)
_SOURCE_ALIAS = re.compile(r'«([^»]+)»\s*\(([^()]+)\)|"([^"\n]+)"\s*\(([^()]+)\)')
_CONNECTORS = frozenset({"і", "й", "та", "and"})
_CLAUSE_WORDS = frozenset(
    {
        "має",
        "мають",
        "містить",
        "містити",
        "повинен",
        "повинні",
        "можна",
        "потрібно",
        "означає",
        "дозволено",
        "does",
        "do",
        "can",
        "should",
        "must",
    }
)
MAX_OBLIGATIONS = 16
MAX_FACETS = 8
_FUNCTION_TOKENS = frozenset(token for word in _FUNCTIONS for token in tokenize(word))


@dataclass(frozen=True)
class Obligation:
    label: str
    tokens: frozenset[str] = frozenset()
    literal: str = ""
    named: bool = False

    def met(self, text: str, context: frozenset[str] = frozenset()) -> bool:
        if self.named and len(self.literal) == 1 and self.literal in _FUNCTIONS:
            return quoted_label_met(self.literal, text)
        if self.literal:
            words = tuple(_normal(word.group()) for word in _WORD.finditer(text))
            needle = tuple(_normal(word.group()) for word in _WORD.finditer(self.literal))
            return bool(needle) and any(
                words[index : index + len(needle)] == needle for index in range(len(words))
            )
        return self.tokens <= (frozenset(tokenize(text)) | context)


@dataclass(frozen=True)
class QuestionObligations:
    subjects: tuple[Obligation, ...] = ()
    facets: tuple[Obligation, ...] = ()
    overflow: bool = False
    ambiguous_label: bool = False

    @property
    def multi_facet(self) -> bool:
        return len(self.facets) > 1

    def missing_subjects(self, text: str, context: frozenset[str] = frozenset()) -> tuple[str, ...]:
        return tuple(item.label for item in self.subjects if not item.met(text, context))

    def facet_hits(self, text: str, context: frozenset[str] = frozenset()) -> frozenset[int]:
        allowed = frozenset(
            token for item in (*self.subjects, *self.facets) for token in tokenize(item.label)
        )
        heads = (_BINDING.split(clause, maxsplit=1)[0] for clause in _CLAUSE.split(text))
        witnesses = [
            head
            for head in heads
            if not self.missing_subjects(head, context)
            and not (
                frozenset(tokenize(head))
                - allowed
                - _FUNCTION_TOKENS
                - _alias_tokens(head, self.subjects)
            )
        ]
        return frozenset(
            index
            for index, item in enumerate(self.facets)
            if any(item.met(head) for head in witnesses)
        )


def _alias_tokens(head: str, subjects: tuple[Obligation, ...]) -> frozenset[str]:
    """Only a quoted name followed by a parenthetical name is an alias declaration.

    No free-standing co-mention grants identity. The original quote is unchanged.
    """
    allowed: set[str] = set()
    for match in _SOURCE_ALIAS.finditer(head):
        names = [value for value in match.groups() if value is not None]
        words = list(_WORD.finditer(names[1]))
        if not 1 <= len(words) <= 3 or not all(word.group()[0].isupper() for word in words):
            continue
        if any(item.named and item.met(name) for name in names for item in subjects):
            allowed.update(tokenize(match.group()))
    return frozenset(allowed)


def _term(word: str, *, literal: bool = False, named: bool = False) -> Obligation:
    tokens = frozenset(tokenize(word))
    if literal or not tokens:
        return Obligation(word, literal=_normal(word), named=named)
    return Obligation(word, tokens=tokens, named=named)


def _property_parts(question: str) -> tuple[list[Obligation], list[Obligation]]:
    match = _PROPERTY.match(question.strip())
    if match is None:
        return [], []
    words = [word.group() for word in _WORD.finditer(question.strip()[match.end() :])]
    while words and _normal(words[0]) in {"is", "are", "the"}:
        words.pop(0)
    if not words or _normal(words[0]) in _CLAUSE_WORDS:
        return [], []
    facets = [_term(words.pop(0))]
    while len(words) >= 2 and _normal(words[0]) in _CONNECTORS:
        words.pop(0)
        facets.append(_term(words.pop(0)))
    # Predicate questions (e.g. duties a role has) are handled by the existing
    # interrogative/declared-subject contract; this grammar claims noun phrases only.
    if any(_normal(word) in _CLAUSE_WORDS for word in words):
        return [], []
    subjects = [_term(word) for word in words if _normal(word) not in _FUNCTIONS]
    if len(facets) == 1 and question_kind(_normal(facets[0].label)) == "duty":
        return [], subjects
    return facets, subjects


def _explicit_subjects(question: str) -> list[Obligation]:
    subjects = []
    for match in _QUOTED.finditer(question):
        value = next(group for group in match.groups() if group is not None)
        subjects.append(_term(value, literal=True, named=True))
    for index, match in enumerate(_WORD.finditer(question)):
        word = match.group()
        has_digit = any(char.isdigit() for char in word)
        identifier = has_digit and (any(char.isalpha() for char in word) or "." in word)
        named = index > 0 and word[0].isupper() and _normal(word) not in _FUNCTIONS
        if identifier or named:
            subjects.append(_term(word, literal=identifier, named=True))
    subjects.extend(_term(match.group(1), literal=True) for match in _VERSION.finditer(question))
    return subjects


def question_obligations(question: str) -> QuestionObligations:
    facets, context = _property_parts(question)
    explicit = _explicit_subjects(question)
    # Identity is the normalized predicate, not its spelling or insertion order.
    subjects = {(item.tokens, item.literal): item for item in [*context, *explicit]}
    distinct_facets = {(item.tokens, item.literal): item for item in facets}
    overflow = len(subjects) > MAX_OBLIGATIONS or len(distinct_facets) > MAX_FACETS

    def ordered(items: Iterable[Obligation]) -> tuple[Obligation, ...]:
        return tuple(sorted(items, key=lambda item: (_normal(item.label), item.literal)))

    return QuestionObligations(
        subjects=ordered(subjects.values())[:MAX_OBLIGATIONS],
        facets=ordered(distinct_facets.values())[:MAX_FACETS],
        overflow=overflow,
        ambiguous_label=ambiguous_trailing_label(question, _FUNCTIONS),
    )


def obligation_version_cap(question: str, configured: int, limit: int) -> int:
    """Spend the existing result budget on separate facts from the same version.

    No extra retrieval, candidate expansion, authority or threshold relaxation.
    The configured cap remains the floor; total result/candidate limits stay intact.
    """
    count = len(question_obligations(question).facets)
    return min(limit, max(configured, count)) if count > 1 else configured
