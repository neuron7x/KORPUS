"""Ліниве згортання надлишковості дає ТОТОЖНИЙ вихід із перерахунком з нуля.

Це рефакторинг у строгому сенсі: та сама функція, інша структура обчислення. Тому
доводиться не «схожість», а ТОТОЖНІСТЬ, і доводиться вона проти ЕТАЛОННОЇ наївної
реалізації, дослівно списаної з тієї, що була до зміни.

Алгебраїчна підстава: `max(S ∪ {x}) = max(max(S), x)`. Максимум асоціативний, а
`jaccard` — частка двох цілих, тож додавань, які могли б накопичити похибку, немає
ЗОВСІМ. Порожній `selected` дає 0.0 — те саме, що `default=0.0` у попередній редакції.
Отже «в межах допуску» тут було б послабленням вимоги, а не її виконанням.

ВИМІРЯНО 02.09.2026 на справжніх прольотах корпусу (256 кандидатів, `limit=8`):

    різних версій 1    62.52 -> 61.52 мс   (-1.6 %)
    різних версій 10  134.48 -> 83.48 мс   (-37.9 %)
    різних версій 20  227.44 -> 103.52 мс  (-54.5 %)

Проміжна редакція, що оновлювала кеш НАПЕРЕД для всіх кандидатів, дала -45 % на
широкому випадку й +15 % на вузькому — тобто ПОГІРШИЛА один із трьох. Її знято:
оптимізація, що погіршує випадок, оптимізацією не є. Ліниве згортання робить рівно ту
роботу, про яку хтось спитав, і не програє ніде.
"""

from __future__ import annotations

import random
from collections import defaultdict
from uuid import UUID

import pytest
from korpus.application.retrieval import diversify_evidence
from korpus.application.retrieval_math import character_ngrams, jaccard
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    RetrievedEvidence,
)

_WORDS = ("варта", "наказ", "командир", "підрозділ", "зброя", "статут", "служба", "пост")


def _evidence(count: int, versions: int, seed: int) -> list[RetrievedEvidence]:
    rng = random.Random(seed)
    items: list[RetrievedEvidence] = []
    for index in range(count):
        version_index = index % versions
        document_id = UUID(int=version_index)
        version_id = UUID(int=10_000 + version_index)
        text = " ".join(rng.choice(_WORDS) for _ in range(rng.randint(8, 40)))
        items.append(
            RetrievedEvidence(
                document=DocumentRecord(
                    id=document_id,
                    canonical_title=f"д{version_index}",
                    corpus_id="c",
                    issuer="i",
                    jurisdiction="UA",
                    document_type="doctrine",
                    access_tier=AccessTier.PUBLIC,
                    classification=Classification.PUBLIC,
                ),
                version=DocumentVersionRecord(
                    id=version_id,
                    document_id=document_id,
                    revision="1",
                    source_hash=f"{version_index:064x}",
                    object_key=f"o{version_index}",
                    mime_type="text/plain",
                    authority=AuthorityClass.OFFICIAL_UA,
                ),
                span=EvidenceSpanRecord(
                    id=UUID(int=20_000 + index),
                    version_id=version_id,
                    ordinal=index,
                    text=text,
                ),
                score=max(0.0, 1.0 - index / (count + 1)),
                query_coverage=0.5,
                rank=index + 1,
            )
        )
    return items


def _reference(
    ranked: list[RetrievedEvidence], *, limit: int, diversity_lambda: float, per_version_cap: int
) -> list[str]:
    """Наївний перерахунок з нуля — дослівно та структура, що була до рефакторингу."""
    from korpus.application.retrieval import (
        AUTHORITY_PRIOR,
        authority_tier,
        authority_tier_floor,
        subject_rank,
    )

    tier_floor = authority_tier_floor(ranked, 0.0)
    selected: list[RetrievedEvidence] = []
    remaining = list(ranked)
    version_counts: defaultdict[str, int] = defaultdict(int)
    grams = {str(item.span.id): character_ngrams(item.span.text) for item in ranked}
    while remaining and len(selected) < limit:
        admissible = [
            item for item in remaining if version_counts[str(item.version.id)] < per_version_cap
        ]
        if not admissible:
            break

        def utility(item: RetrievedEvidence) -> tuple[float, float, float, float, str, int]:
            redundancy = max(
                (
                    jaccard(grams[str(item.span.id)], grams[str(other.span.id)])
                    for other in selected
                ),
                default=0.0,
            )
            return (
                subject_rank(item, frozenset()),
                authority_tier(item, AUTHORITY_PRIOR, tier_floor),
                diversity_lambda * item.score - (1 - diversity_lambda) * redundancy,
                item.score,
                item.version.source_hash,
                -item.span.ordinal,
            )

        winner = max(admissible, key=utility)
        selected.append(winner)
        version_counts[str(winner.version.id)] += 1
        remaining.remove(winner)
    return [str(item.span.id) for item in selected]


@pytest.mark.parametrize("versions", [1, 2, 5, 17, 64])
@pytest.mark.parametrize("per_version_cap", [1, 3])
def test_lazy_folding_equals_the_naive_recomputation(versions: int, per_version_cap: int):
    """Головне твердження: ТОТОЖНІСТЬ, не близькість."""
    ranked = _evidence(count=64, versions=versions, seed=versions * 31 + per_version_cap)
    produced = diversify_evidence(
        ranked, limit=8, diversity_lambda=0.82, per_version_cap=per_version_cap
    )
    expected = _reference(ranked, limit=8, diversity_lambda=0.82, per_version_cap=per_version_cap)
    assert [str(item.span.id) for item in produced] == expected


def test_the_reference_is_not_trivially_equal():
    """Негативний контроль на сам ЕТАЛОН.

    Без нього обидві реалізації могли б повертати, скажімо, порожній список, і тест
    вище лишався б зеленим, нічого не доводячи.
    """
    ranked = _evidence(count=64, versions=17, seed=7)
    expected = _reference(ranked, limit=8, diversity_lambda=0.82, per_version_cap=1)
    assert len(expected) == 8, "еталон мусить справді щось обирати"
    assert len(set(expected)) == 8, "еталон мусить обирати РІЗНІ прольоти"
    other = _reference(ranked, limit=8, diversity_lambda=1.0, per_version_cap=1)
    assert other != expected, "інша λ мусить давати інший вибір, інакше λ ні на що не впливає"


def test_ranks_are_dense_and_start_at_one():
    """Ранги — частина виходу, і рефакторинг не сміє їх зрушити."""
    produced = diversify_evidence(_evidence(64, 17, seed=3), limit=8, per_version_cap=1)
    assert [item.rank for item in produced] == list(range(1, len(produced) + 1))
