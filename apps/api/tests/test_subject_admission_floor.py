"""Поріг допуску карав документ за те, заради чого поріг існує.

Стаття «Обов'язки: Вивідний» має найнижчу сиру оцінку у видачі (0.181 проти порога
0.25) саме тому, що не повторює слів питання, — і саме вона є відповіддю. Допуск за
ОГОЛОШЕНИМ предметом знімає лексичні пороги й НЕ знімає структурних: затвердженість
версії та нормативність авторитету стоять для всіх однаково.
"""

from __future__ import annotations

from types import SimpleNamespace

from korpus.application.evidence_admission import evidence_is_eligible
from korpus.application.risk import RiskThresholds
from korpus.domain.models import AuthorityClass

THRESHOLDS = RiskThresholds(
    minimum_score=0.25,
    minimum_query_coverage=0.5,
    minimum_support_score=0.25,
    minimum_authority=0.0,
)


def _item(score: float, *, approved: bool = True) -> object:
    #: Справжній клас авторитету, а не двійник: `candidate_margins` бере з нього
    #: пріор за ключем, і підроблений об'єкт зробив би тест зеленим від TypeError.
    authority = AuthorityClass.OFFICIAL_UA
    return SimpleNamespace(
        score=score,
        query_coverage=0.0,
        version=SimpleNamespace(
            review_state=SimpleNamespace(value="approved" if approved else "draft"),
            authority=authority,
        ),
    )


def test_a_declared_subject_passes_a_floor_its_wording_cannot_clear() -> None:
    assert evidence_is_eligible(_item(0.181), THRESHOLDS, declares_the_subject=True)


def test_the_same_item_without_the_declaration_is_refused() -> None:
    """Негативний контроль: поріг лишається порогом для всіх інших."""
    assert not evidence_is_eligible(_item(0.181), THRESHOLDS)


def test_the_declaration_does_not_lift_the_structural_bar() -> None:
    """Допуск за предметом каже «це про того, кого спитали», а не «цьому можна більше».

    Незатверджена версія лишається незатвердженою, хоч би що вона про себе оголосила.
    """
    assert not evidence_is_eligible(
        _item(0.9, approved=False), THRESHOLDS, declares_the_subject=True
    )
