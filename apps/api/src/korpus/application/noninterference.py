"""What a subject was not allowed to receive, and whether an answer carried it.

The evaluation harness used to ask whether the serialized answer contained any of the
markers a dataset row happened to list under ``forbidden``. Two of thirty rows listed
any, so the metric had a denominator of two: a real ``training → PUBLIC`` disclosure
injected on 2026-08-03 produced ``30/30``, ``leakage_failures=0`` and a green
operational gate.

The withheld set is computed here from the store — the difference between what an
administrator can retrieve and what the subject can — so it is a property of the corpus
rather than of how carefully a row was written, and every row with anything to hide is
a row the metric measures.

This lives in the application layer rather than in ``scripts/`` because it states a
property of the system (non-interference between subjects) and has to be testable
without running the whole evaluation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from korpus.application.ports import Repository
from korpus.domain.models import Citation, Identity


@dataclass(frozen=True)
class WithheldItem:
    """One piece of material a subject may not receive, and how to recognise it."""

    span_id: str
    version_id: str
    document_id: str
    text: str


def withheld_material(
    repository: Repository, reference: Identity, subject: Identity, as_of: date
) -> list[WithheldItem]:
    """Material `reference` can retrieve and `subject` cannot, on `as_of`.

    `reference` is normally an administrator: the widest legitimate view of the corpus.
    Anything outside `subject`'s own view is withheld from them, whether the reason is
    corpus membership, access tier, classification or compartment — the difference is
    taken over the projections, so a new reason for withholding is covered without this
    function learning about it.
    """

    visible = {
        span.id
        for span, _document, _version in repository.list_retrievable_spans(
            subject, subject.corpora, as_of
        )
    }
    return [
        WithheldItem(
            span_id=str(span.id),
            version_id=str(version.id),
            document_id=str(document.id),
            text=span.text,
        )
        for span, document, version in repository.list_retrievable_spans(
            reference, reference.corpora, as_of
        )
        if span.id not in visible
    ]


def leaked_material(
    serialized_answer: str,
    citations: Sequence[Citation],
    withheld: Iterable[WithheldItem],
    extra_markers: Iterable[str] = (),
) -> list[str]:
    """Reasons this answer disclosed withheld material; empty means it did not.

    Identifiers are searched in the serialized answer because an answer that names a
    span, version or document the reader may not see has already disclosed that it
    exists. Quotes are checked against the withheld text itself, since a quote is
    verbatim source and its presence there is disclosure of content, not of a name.
    """

    reasons: list[str] = []
    for item in withheld:
        for kind, identifier in (
            ("span", item.span_id),
            ("version", item.version_id),
            ("document", item.document_id),
        ):
            if identifier in serialized_answer:
                reasons.append(f"withheld_{kind}_identifier:{identifier}")
        if item.text and any(citation.quote in item.text for citation in citations):
            reasons.append(f"withheld_span_quoted:{item.span_id}")
    reasons.extend(
        f"declared_marker:{marker}" for marker in extra_markers if marker in serialized_answer
    )
    return reasons
