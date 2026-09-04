"""Ознаки доказу PEC: сама формула не мала тесту, лише вироджені ранні виходи.

Вимір покриття гілок 04.09.2026: у `score_concentration` виконувались тільки шляхи
«порожньо» й «один елемент», а обчислення ентропії — жодного разу; у `redundancy`
не виконувався шлях із двома й більше доказами, тобто те, заради чого функція є.
Ознака, чиє обчислення не міряли, годує контролер числом, якого ніхто не бачив.
"""

from __future__ import annotations

import math
from datetime import date

import pytest
from korpus.application.pec_evidence_features import redundancy, score_concentration
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    RetrievedEvidence,
    ReviewState,
)


def _evidence(text: str) -> RetrievedEvidence:
    document = DocumentRecord(
        canonical_title="Статут зв'язку",
        corpus_id="public",
        issuer="МОУ",
        jurisdiction="UA",
        document_type="doctrine",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1.0",
        source_hash="a" * 64,
        object_key="docs/a",
        mime_type="text/plain",
        publication_date=date(2025, 1, 1),
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.APPROVED,
    )
    span = EvidenceSpanRecord(version_id=version.id, ordinal=0, section="Зв'язок", text=text)
    return RetrievedEvidence(
        span=span, document=document, version=version, score=0.8, query_coverage=0.75
    )


def test_concentration_is_one_when_a_single_candidate_holds_all_the_score() -> None:
    """Один кандидат — уся маса на ньому; це визначення концентрації, не окремий випадок."""
    assert score_concentration([0.9]) == 1.0


def test_concentration_falls_as_the_score_mass_spreads_out() -> None:
    """Порядок важливіший за абсолютне число: рівний розподіл мусить бути найнижчим.

    Без цього тесту формула могла б повертати сталу — і всі гілки контролера, що
    читають концентрацію, судили б за числом, яке ні на що не реагує.
    """
    peaked = score_concentration([0.9, 0.05, 0.05])
    even = score_concentration([0.3, 0.3, 0.3])
    assert 0.0 <= even < peaked <= 1.0
    assert math.isclose(even, 0.0, abs_tol=1e-9)


def test_concentration_is_scale_free() -> None:
    """Множення всіх оцінок на константу не змінює того, наскільки вони зосереджені."""
    assert math.isclose(
        score_concentration([0.2, 0.6, 0.2]), score_concentration([2.0, 6.0, 2.0]), abs_tol=1e-9
    )


@pytest.mark.parametrize("scores", [[0.0, 0.0], [-1.0, -2.0], [0.0, -0.5]])
def test_concentration_of_a_zero_mass_is_zero_not_an_error(scores: list[float]) -> None:
    """Нульова сума — це «немає чого зосереджувати», а не ділення на нуль.

    Від'ємні оцінки підрізаються нулем, тож сума може стати нульовою і на непорожньому
    переліку. Виняток тут зупинив би добування ознак посеред запиту.
    """
    assert score_concentration(scores) == 0.0


def test_concentration_of_nothing_is_zero() -> None:
    assert score_concentration([]) == 0.0


def test_redundancy_of_fewer_than_two_spans_is_zero() -> None:
    """Надлишковість — властивість ПАРИ; на одному прольоті її не існує."""
    assert redundancy([]) == 0.0
    assert redundancy([_evidence("маскування позиції")]) == 0.0


def test_redundancy_separates_repeated_spans_from_distinct_ones() -> None:
    """Дві копії одного тексту — максимум; два різні тексти — менше.

    Це та ознака, за якою контролер вирішує, чи новий пошук щось додасть. Якби вона
    не розрізняла ці два випадки, «шукати ще» коштувало б завжди однаково.
    """
    same = redundancy([_evidence("маскування позиції"), _evidence("маскування позиції")])
    different = redundancy([_evidence("маскування позиції"), _evidence("накладання турнікету")])
    assert math.isclose(same, 1.0, abs_tol=1e-9)
    assert different < same
