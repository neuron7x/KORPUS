from __future__ import annotations

import random
import unicodedata

from korpus.application.retrieval import RetrievalWeights, score_candidates


def _by_text(texts, scored):
    return {texts[item.index]: item for item in scored}


def test_unicode_normalization_is_semantics_preserving():
    text = "Зв’язок підрозділу"
    nfd = unicodedata.normalize("NFD", text)
    a = score_candidates(text, [text])[0]
    b = score_candidates(nfd, [nfd])[0]
    assert a.normalized_score == b.normalized_score
    assert a.query_coverage == b.query_coverage


def test_candidate_permutation_is_equivariant_for_unique_texts():
    texts = [
        "тактична медицина",
        "засоби зв’язку",
        "інженерна підготовка",
        "логістичне забезпечення",
    ]
    query = "засоби зв’язку"
    baseline = _by_text(texts, score_candidates(query, texts))
    shuffled = list(texts)
    random.Random(20260820).shuffle(shuffled)
    observed = _by_text(shuffled, score_candidates(query, shuffled))
    assert baseline.keys() == observed.keys()
    for text in baseline:
        assert baseline[text].normalized_score == observed[text].normalized_score


def test_zero_weight_semantic_channel_is_noninterfering():
    texts = ["офіційний порядок дій", "інший матеріал"]
    weights = RetrievalWeights()
    low = score_candidates("порядок дій", texts, semantic_scores=[0.0, 0.0], weights=weights)
    high = score_candidates("порядок дій", texts, semantic_scores=[1.0, 1.0], weights=weights)
    assert [x.normalized_score for x in low] == [x.normalized_score for x in high]


def test_increasing_positive_weight_component_cannot_reduce_same_candidate_score():
    texts = ["порядок евакуації"]
    low = score_candidates("порядок", texts, authority_scores=[0.2])[0].normalized_score
    high = score_candidates("порядок", texts, authority_scores=[0.9])[0].normalized_score
    assert high >= low


def test_seeded_replay_is_bitwise_deterministic():
    rng = random.Random(7)
    vocabulary = ["зв'язок", "медицина", "навчання", "порядок", "забезпечення", "підрозділ"]
    for _ in range(100):
        texts = [" ".join(rng.sample(vocabulary, 3)) for _ in range(12)]
        query = " ".join(rng.sample(vocabulary, 2))
        first = score_candidates(query, texts)
        second = score_candidates(query, texts)
        assert first == second
