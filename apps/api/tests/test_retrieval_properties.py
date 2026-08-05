from __future__ import annotations

import random

from korpus.application.retrieval import character_ngrams, score_candidates, tokenize


def _ranking(query: str, texts: list[str]) -> list[str]:
    scored = score_candidates(query, texts, [False] * len(texts))
    return [texts[item.index] for item in sorted(scored, key=lambda item: -item.normalized_score)]


def test_tokenization_is_unicode_and_case_normalization_invariant():
    assert tokenize("ЖУРНАЛ Перевірок") == tokenize("журнал перевірок")
    assert tokenize("і\u0308") == tokenize("ї")


def test_retrieval_ranking_is_permutation_invariant_for_unique_scores():
    query = "дата відповідальна особа журнал"
    texts = [
        "Кожен запис журналу має містити дату та відповідальну особу.",
        "Погода завтра буде мінливою.",
        "Журнал містить лише назву.",
    ]
    expected = _ranking(query, texts)
    for seed in range(30):
        shuffled = texts.copy()
        random.Random(seed).shuffle(shuffled)
        assert _ranking(query, shuffled) == expected


def test_irrelevant_documents_do_not_displace_exact_relevant_document():
    query = "кожен запис журналу дата відповідальна особа"
    target = "Кожен запис журналу має містити дату та відповідальну особу."
    noise = [f"Нерелевантний текст про погоду номер {index}." for index in range(200)]
    ranking = _ranking(query, [*noise, target])
    assert ranking[0] == target


def test_score_bounds_hold_over_seeded_random_inputs():
    source = random.Random(7312026)
    vocabulary = ["журнал", "дата", "особа", "порядок", "перевірка", "навчання", "документ"]
    for _ in range(200):
        query = " ".join(source.sample(vocabulary, source.randint(1, 4)))
        texts = [
            " ".join(source.choice(vocabulary) for _ in range(source.randint(1, 30)))
            for _ in range(source.randint(1, 20))
        ]
        for item in score_candidates(query, texts, [False] * len(texts)):
            assert 0 <= item.normalized_score <= 1
            assert 0 <= item.query_coverage <= 1
            assert 0 <= item.character_score <= 1


def test_character_ngrams_are_deterministic_and_nonempty_for_text():
    assert character_ngrams("Перевірка") == character_ngrams("ПЕРЕВІРКА")
    assert character_ngrams("abc") == frozenset({"abc"})
