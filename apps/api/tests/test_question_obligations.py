"""Contrastive applicability controls for the explicitly supported question grammar."""

from __future__ import annotations

import hashlib
from itertools import permutations
from uuid import uuid4

import pytest
from korpus.application.answer_obligations import unmet_answer_obligations
from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.application.question_obligations import (
    obligation_version_cap,
    question_obligations,
)
from korpus.application.retrieval_math import tokenize
from korpus.application.risk import RiskThresholds

from apps.api.tests.test_intra_span_contradiction import _evidence


def _extract(question, evidence, max_claims=4):
    service = ExtractiveAnswerService.__new__(ExtractiveAnswerService)
    service.answer_policy = AnswerPolicy(0.18, 0.5, 0.18, "obligation-test", max_claims)
    return service._extract(
        evidence,
        frozenset(tokenize(question or " ".join(item.span.text for item in evidence))),
        RiskThresholds(0.18, 0.5, 0.18, 0.0),
        question,
    )


@pytest.mark.parametrize(
    ("question", "wrong", "right"),
    [
        ("Який колір картки архіву Полтави?", "Львова", "Полтави"),
        ("який колір картки архіву полтави?", "львова", "Полтава"),
        ("Який колір картки архіву Сум?", "Одеси", "Сум"),
        ("який колір картки архіву смарагду?", "Бурштину", "Смарагд"),
        ("Який колір картки архіву QZ-17?", "QZ-170", "QZ-17"),
        ("Який колір картки архіву v2.1?", "v2.10", "v2.1"),
        ("Який колір картки архіву версії 2?", "версії 3", "версії 2"),
    ],
)
def test_subject_is_a_conjunctive_obligation(question, wrong, right):
    foreign = _evidence(f"Колір картки архіву {wrong} — синій.")
    matching = _evidence(f"Колір картки архіву {right} — синій.")
    assert _extract(question, [foreign])[0] == []
    claims, citations, _ = _extract(question, [matching])
    assert claims and citations
    assert unmet_answer_obligations(question, claims, citations, [matching]) == ()


def test_unknown_lowercase_subject_cannot_disappear_into_overlap():
    question = "який колір картки архіву невідомограда?"
    evidence = _evidence("Колір картки архіву Березового — синій.")
    assert _extract(question, [evidence])[0] == []
    assert "невідомограда" in unmet_answer_obligations(question, [], [], [evidence])


def test_source_stated_aliases_are_literal_evidence_not_an_external_alias_map():
    source = _evidence("Колір картки архіву «Сокіл» (Sokil) — синій.")
    for alias in ("Сокіл", "Sokil"):
        question = f"Який колір картки архіву «{alias}»?"
        assert _extract(question, [source])[0]
        assert _extract(f"Який колір картки архіву {alias}?", [source])[0]
    assert _extract("Який колір картки архіву «Falcon»?", [source])[0] == []


def test_explicit_name_is_required_outside_the_property_grammar():
    contract = question_obligations("Що відомо про «Зелена Вежа»?")
    assert contract.missing_subjects("Відомо про інший архів.")
    assert not contract.missing_subjects("Архів «Зелена Вежа» приймає записи.")


def test_final_gate_rechecks_subject_after_substituted_extraction():
    evidence = _evidence("Колір картки архіву Кедра — синій.")
    claims, citations, _ = _extract("", [evidence])
    assert claims and citations
    failures = unmet_answer_obligations("Що відомо про Липу?", claims, citations, [evidence])
    assert "Липу" in failures


def test_invalid_fact_cannot_hide_behind_another_valid_claim():
    right = _evidence("Колір картки архіву Липи — синій.")
    foreign = _evidence("Колір картки архіву Кедра — синій для архіву Липи.")
    claims, citations, _ = _extract("", [right, foreign])
    assert len(claims) == 2
    failures = unmet_answer_obligations(
        "Який колір картки архіву Липи?", claims, citations, [right, foreign]
    )
    assert "question_fact_binding" in failures


@pytest.mark.parametrize("question", ["Який колір картки архіву Липи?", "Що містить запис?"])
def test_every_claim_needs_its_own_literal_citation_even_with_a_shared_span(question):
    source = _evidence("Колір картки архіву Липи — синій. Колір картки архіву Кедра — зелений.")
    claims, citations, _ = _extract("Який колір картки архіву Липи?", [source])
    foreign = claims[0].model_copy(update={"text": "Колір картки архіву Кедра — зелений."})
    assert unmet_answer_obligations(question, [*claims, foreign], citations, [source]) == (
        "claim_quote_binding",
    )


def test_every_claim_reference_and_citation_needs_a_matching_counterpart():
    source = _evidence("Колір картки архіву Липи — синій.")
    claims, citations, _ = _extract("Який колір картки архіву Липи?", [source])
    dangling = claims[0].model_copy(update={"evidence_span_ids": (source.span.id, uuid4())})
    assert unmet_answer_obligations("Що містить запис?", [dangling], citations, [source]) == (
        "claim_quote_binding",
    )
    extra = citations[0].model_copy(update={"quote": "Another source statement."})
    assert unmet_answer_obligations("Що містить запис?", claims, [*citations, extra], [source]) == (
        "claim_quote_binding",
    )


def test_two_facets_are_covered_by_two_exact_sentences_in_one_span():
    source = _evidence("Колір картки архіву — синій. Розмір картки архіву — великий.")
    question = "Який колір і розмір картки архіву?"
    claims, citations, _ = _extract(question, [source])
    assert len(claims) == len(citations) == 2
    assert unmet_answer_obligations(question, claims, citations, [source]) == ()
    for citation in citations:
        assert source.span.text[citation.quote_start : citation.quote_end] == citation.quote
        assert citation.quote_hash == hashlib.sha256(citation.quote.encode()).hexdigest()
        assert citation.span_hash == source.span.text_hash


def test_missing_facet_is_not_a_complete_answer():
    source = _evidence("Колір картки архіву — синій.")
    question = "Який колір і розмір картки архіву?"
    claims, citations, _ = _extract(question, [source])
    assert claims
    assert unmet_answer_obligations(question, claims, citations, [source]) == ("розмір",)


def test_one_exact_sentence_can_witness_both_requested_properties():
    source = _evidence("Колір і розмір картки архіву — синій та великий.")
    question = "Який колір і розмір картки архіву?"
    claims, citations, _ = _extract(question, [source])
    assert len(claims) == len(citations) == 1
    assert unmet_answer_obligations(question, claims, citations, [source]) == ()


def test_facets_cannot_be_laundered_across_versions():
    color = _evidence("Колір картки архіву — синій.")
    size = _evidence("Розмір картки архіву — великий.")
    question = "Який колір і розмір картки архіву?"
    # Adversarial extraction carries valid quotes but lacks a same-version witness.
    color_claims, color_citations, _ = _extract("", [color])
    size_claims, size_citations, _ = _extract("", [size])
    assert unmet_answer_obligations(
        question, color_claims + size_claims, color_citations + size_citations, [color, size]
    )


def test_same_version_facets_are_order_invariant_and_claim_budgeted():
    color = _evidence("Колір картки архіву — синій.")
    size = color.model_copy(
        update={
            "span": color.span.model_copy(
                update={
                    "id": uuid4(),
                    "ordinal": 1,
                    "text": "Розмір картки архіву — великий.",
                    "text_hash": hashlib.sha256(
                        "Розмір картки архіву — великий.".encode()
                    ).hexdigest(),
                }
            )
        }
    )
    irrelevant = _evidence("Колір картки архіву — синій.")
    question = "Який колір і розмір картки архіву?"
    results = []
    for items in permutations([color, size, irrelevant]):
        claims, citations, _ = _extract(question, list(items))
        assert unmet_answer_obligations(question, claims, citations, list(items)) == ()
        assert len({citation.version_id for citation in citations}) == 1
        results.append(
            ([claim.text for claim in claims], [citation.model_dump() for citation in citations])
        )
    assert all(result == results[0] for result in results)
    claims, citations, _ = _extract(question, [color, size], max_claims=1)
    assert len(claims) == 1
    assert unmet_answer_obligations(question, claims, citations, [color, size])


def test_duplicate_sentences_do_not_spend_claim_budget_or_multiply_sources():
    sentence = "Кожен запис має містити дату та відповідальну особу."
    sources = [_evidence(sentence), _evidence(sentence)]
    claims, citations, _ = _extract("Що має містити кожен запис?", sources)
    assert len(claims) == len(citations) == 1
    assert claims[0].text == sentence


def test_generic_question_remains_answerable_without_invented_entity_constraints():
    source = _evidence("Кожен запис має містити дату та відповідальну особу.")
    question = "Що має містити кожен запис?"
    claims, citations, _ = _extract(question, [source])
    assert claims and not unmet_answer_obligations(question, claims, citations, [source])


def test_genitive_duties_preserve_subject_without_inventing_a_literal_property():
    obligations = question_obligations("Які обов'язки архіваріуса?")
    assert obligations.facets == ()
    assert obligations.subjects
    assert not obligations.missing_subjects("Архіваріус зобов'язаний перевіряти картки.")
    assert obligations.missing_subjects("Бібліотекар зобов'язаний перевіряти картки.")


def test_english_property_list_and_identifier_keep_the_same_contract():
    source = _evidence("The archive card A-7 color is blue. The archive card A-7 size is large.")
    question = "What are the color and size of the archive card A-7?"
    claims, citations, _ = _extract(question, [source])
    assert len(claims) == 2
    assert unmet_answer_obligations(question, claims, citations, [source]) == ()


def test_obligation_capacity_fails_closed_and_never_increases_result_budget():
    question = "Який колір і розмір і обсяг і формат і вага картки архіву?"
    assert obligation_version_cap(question, 1, 3) == 3
    assert obligation_version_cap("Що містить картка?", 1, 8) == 1
    long_question = "Який колір " + " ".join(f"Object-{index}" for index in range(24)) + "?"
    assert question_obligations(long_question).overflow
    assert unmet_answer_obligations(long_question, [], [], []) == (
        "question_obligation_budget_exceeded",
    )
