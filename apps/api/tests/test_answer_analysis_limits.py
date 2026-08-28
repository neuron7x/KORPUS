"""Authority confinement, contradiction detection and the limitations an answer declares.

These three functions decide what an extractive answer is allowed to say about itself.
`confine_to_top_authority` drops evidence a higher-ranked source outranks;
`find_contradiction` refuses rather than choosing between conflicting sources; the
limitation list names every reason the answer is narrower than it looks.

Measured on 2026-08-28 the module sat at 86.1% branch coverage with the empty case, the
repeated-source case and the multiple-current-versions case untaken. Each one is a way an
answer can look better supported than it is: four citations from one version read as four
sources, and two current versions of one document mean the corpus disagrees with itself.
"""

from __future__ import annotations

import hashlib
from datetime import date
from uuid import uuid4

from korpus.application.answer_analysis import (
    confine_to_top_authority,
    find_contradiction,
)
from korpus.domain.models import (
    AuthorityClass,
    Citation,
    Claim,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    RetrievedEvidence,
    ReviewState,
)


def _evidence(
    text: str = "Кожен запис має містити дату.",
    *,
    authority: AuthorityClass = AuthorityClass.OFFICIAL_UA,
    publication_date: date | None = date(2026, 1, 1),
    document: DocumentRecord | None = None,
) -> RetrievedEvidence:
    document = document or DocumentRecord(
        canonical_title="Джерело",
        corpus_id="public",
        issuer="Authorized Test Authority",
        jurisdiction="UA",
        document_type="order",
        access_tier=0,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1.0",
        source_hash="ab" * 32,
        object_key="objects/x",
        mime_type="text/plain",
        authority=authority,
        review_state=ReviewState.APPROVED,
        publication_date=publication_date,
    )
    span = EvidenceSpanRecord(version_id=version.id, ordinal=0, text=text)
    return RetrievedEvidence(
        span=span, document=document, version=version, score=0.9, query_coverage=1.0
    )


def _claim(evidence: RetrievedEvidence) -> Claim:
    return Claim(
        text=evidence.span.text,
        evidence_span_ids=(evidence.span.id,),
        support_score=1.0,
        query_coverage=1.0,
    )


def _citation(evidence: RetrievedEvidence) -> Citation:
    return Citation(
        document_id=evidence.document.id,
        version_id=evidence.version.id,
        span_id=evidence.span.id,
        title=evidence.document.canonical_title,
        revision=evidence.version.revision,
        quote=evidence.span.text,
        quote_start=0,
        quote_end=len(evidence.span.text),
        quote_hash=hashlib.sha256(evidence.span.text.encode("utf-8")).hexdigest(),
        source_hash=evidence.version.source_hash,
    )


def test_confinement_over_nothing_returns_two_empty_lists() -> None:
    """`max()` over an empty sequence raises; the guard is what keeps a no-evidence
    answer a refusal rather than a crash inside the ranking step."""
    assert confine_to_top_authority([]) == ([], [])


def test_only_the_highest_authority_class_survives_confinement() -> None:
    """Rank is not outweighed by similarity: a closer match from a weaker source loses."""
    official = _evidence(authority=AuthorityClass.OFFICIAL_UA)
    secondary = _evidence(authority=AuthorityClass.ANALYTICAL)
    confined, outranked = confine_to_top_authority([secondary, official])
    assert [item.version.authority for item in confined] == [AuthorityClass.OFFICIAL_UA]
    assert [item.version.authority for item in outranked] == [AuthorityClass.ANALYTICAL]


def test_evidence_of_one_authority_class_is_never_outranked_by_itself() -> None:
    """The dual: confinement that emptied a single-class result would refuse everything."""
    first = _evidence()
    second = _evidence()
    confined, outranked = confine_to_top_authority([first, second])
    assert len(confined) == 2
    assert outranked == []


def test_two_current_versions_of_one_document_stop_the_answer() -> None:
    """One document with two current versions means the corpus contradicts itself.

    Answering from either would be a choice the system is not entitled to make, and the
    conflict is in the corpus rather than in the question.
    """
    document = DocumentRecord(
        canonical_title="Наказ",
        corpus_id="public",
        issuer="Authorized Test Authority",
        jurisdiction="UA",
        document_type="order",
        access_tier=0,
        classification=Classification.PUBLIC,
    )
    first = _evidence(document=document)
    second = _evidence(document=document)
    assert first.version.id != second.version.id

    reason = find_contradiction(
        [_claim(first)],
        [_citation(first), _citation(second)],
        [first, second],
    )
    assert reason == f"multiple_current_versions:{document.id}"


def test_one_current_version_per_document_is_not_a_contradiction() -> None:
    """The dual: reporting a conflict for every multi-citation answer would refuse all."""
    first = _evidence()
    second = _evidence(text="Журнал зберігається протягом трьох років.")
    assert (
        find_contradiction(
            [_claim(first)],
            [_citation(first), _citation(second)],
            [first, second],
        )
        is None
    )


def test_an_unrelated_document_id_does_not_collide_with_another(monkeypatch) -> None:
    """Grouping is per document; two documents each with one version stay separate."""
    first = _evidence()
    second = _evidence()
    assert first.document.id != second.document.id
    assert uuid4() not in {first.document.id, second.document.id}
    assert (
        find_contradiction(
            [_claim(first)],
            [_citation(first), _citation(second)],
            [first, second],
        )
        is None
    )


def test_two_claims_that_contradict_each_other_stop_the_answer() -> None:
    """The pairwise pass over claims, which no earlier test reached.

    Two claims drawn from the same corpus can oppose each other even when every citation
    is sound and every document has one current version. Answering with both would put
    the contradiction in front of the reader as if it were one position.
    """
    evidence = _evidence(text="Ведення журналу є обов'язковим для кожного підрозділу.")
    opposite = _evidence(text="Ведення журналу не є обов'язковим для підрозділів забезпечення.")
    reason = find_contradiction(
        [_claim(evidence), _claim(opposite)],
        [_citation(evidence)],
        [evidence, opposite],
    )
    assert reason is not None
    assert "opposed_negation" in reason or reason.startswith("refuted_by_evidence:")


def test_claims_that_merely_differ_are_not_a_contradiction() -> None:
    """The dual: reporting every multi-claim answer as contradictory would refuse all."""
    first = _evidence(text="Журнал зберігається протягом трьох років.")
    second = _evidence(text="Записи вносяться відповідальною особою.")
    assert (
        find_contradiction(
            [_claim(first), _claim(second)],
            [_citation(first)],
            [first, second],
        )
        is None
    )


def test_repeated_citations_of_one_version_are_named_as_one_source() -> None:
    """Four citations from one version read as four sources unless the answer says so.

    The limitation is the whole point: an extractive answer's apparent support is the
    number of citations, and a reader counting them would overstate the evidence by
    three.
    """
    from korpus.application.answer_analysis import source_limitations

    evidence = _evidence()
    citations = [_citation(evidence), _citation(evidence), _citation(evidence)]
    limitations = source_limitations(citations, [], [evidence])
    assert any("більше ніж один раз" in item for item in limitations)

    single = source_limitations([_citation(evidence)], [], [evidence])
    assert not any("більше ніж один раз" in item for item in single)


def test_evidence_dropped_by_authority_rank_is_named() -> None:
    """Silence about outranked evidence reads as though it never existed."""
    from korpus.application.answer_analysis import source_limitations

    used = _evidence()
    outranked = _evidence(authority=AuthorityClass.ANALYTICAL)
    limitations = source_limitations([_citation(used)], [outranked], [used])
    assert any("нижчого рангу" in item for item in limitations)


def test_a_citation_from_an_undated_source_is_named() -> None:
    """Without a publication date the lower bound of validity is a library stamp."""
    from korpus.application.answer_analysis import source_limitations

    undated = _evidence(publication_date=None)
    limitations = source_limitations([_citation(undated)], [], [undated])
    assert any("без встановленої дати" in item for item in limitations)
