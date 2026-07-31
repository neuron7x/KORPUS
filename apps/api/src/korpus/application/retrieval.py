from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date

from korpus.application.ports import Repository, Retriever
from korpus.domain.models import Identity, RetrievedEvidence

TOKEN_PATTERN = re.compile(r"[\w'’\-]{2,}", re.UNICODE)
STOP_WORDS = {
    "але", "без", "був", "була", "були", "для", "його", "коли", "про", "та", "так", "це", "що",
    "який", "яка", "яке", "які", "має", "мати", "the", "and", "for", "from", "that", "this", "with",
}


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def tokenize(text: str) -> list[str]:
    return [token for token in TOKEN_PATTERN.findall(normalize_text(text)) if token not in STOP_WORDS]


def character_ngrams(text: str, n: int = 3) -> frozenset[str]:
    compact = re.sub(r"\s+", " ", normalize_text(text)).strip()
    if len(compact) < n:
        return frozenset({compact}) if compact else frozenset()
    return frozenset(compact[index : index + n] for index in range(len(compact) - n + 1))


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))


@dataclass(frozen=True)
class BM25Parameters:
    k1: float = 1.5
    b: float = 0.75


@dataclass(frozen=True)
class ScoredCandidate:
    index: int
    lexical_score: float
    query_coverage: float
    character_score: float
    authority_bonus: float
    phrase_bonus: float

    @property
    def normalized_score(self) -> float:
        lexical = 1 - math.exp(-self.lexical_score / 3)
        combined = (
            lexical * 0.58
            + self.query_coverage * 0.22
            + self.character_score * 0.12
            + self.authority_bonus
            + self.phrase_bonus
        )
        return min(1.0, max(0.0, combined))


def score_candidates(
    query: str,
    texts: list[str],
    official: list[bool],
    parameters: BM25Parameters = BM25Parameters(),
) -> list[ScoredCandidate]:
    if len(texts) != len(official):
        raise ValueError("texts and authority flags must have equal length")
    query_tokens = tokenize(query)
    if not query_tokens or not texts:
        return []
    tokenized = [tokenize(text) for text in texts]
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    average_length = sum(len(tokens) for tokens in tokenized) / max(len(tokenized), 1)
    query_set = set(query_tokens)
    query_grams = character_ngrams(query)
    scored: list[ScoredCandidate] = []
    for index, tokens in enumerate(tokenized):
        if not tokens:
            continue
        frequencies = Counter(tokens)
        bm25 = 0.0
        for term in query_set:
            frequency = frequencies.get(term, 0)
            if frequency == 0:
                continue
            df = document_frequency[term]
            inverse_document_frequency = math.log(
                1 + (len(tokenized) - df + 0.5) / (df + 0.5)
            )
            denominator = frequency + parameters.k1 * (
                1 - parameters.b + parameters.b * len(tokens) / max(average_length, 1)
            )
            bm25 += inverse_document_frequency * (
                frequency * (parameters.k1 + 1)
            ) / denominator
        query_coverage = len(query_set.intersection(tokens)) / len(query_set)
        character_score = jaccard(query_grams, character_ngrams(texts[index]))
        phrase_bonus = 0.08 if normalize_text(query) in normalize_text(texts[index]) else 0.0
        authority_bonus = 0.06 if official[index] else 0.0
        scored.append(
            ScoredCandidate(
                index=index,
                lexical_score=bm25,
                query_coverage=query_coverage,
                character_score=character_score,
                authority_bonus=authority_bonus,
                phrase_bonus=phrase_bonus,
            )
        )
    return scored


class HybridLexicalRetriever(Retriever):
    """Deterministic BM25 + character-ngram retriever.

    The repository performs the authorization filter in SQL before any text is
    returned to this component. The retriever therefore cannot observe higher-
    tier spans, which is the noninterference boundary.
    """

    def __init__(
        self,
        repository: Repository,
        parameters: BM25Parameters = BM25Parameters(),
        candidate_budget: int = 256,
    ) -> None:
        if candidate_budget < 8:
            raise ValueError("candidate_budget must be at least 8")
        self.repository = repository
        self.parameters = parameters
        self.candidate_budget = candidate_budget

    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int = 8,
    ) -> list[RetrievedEvidence]:
        candidates = self.repository.search_retrievable_spans(
            identity, corpus_ids, as_of, text, self.candidate_budget
        )
        if not candidates:
            return []
        component_scores = score_candidates(
            text,
            [span.text for span, _, _ in candidates],
            [version.authority.value.startswith("official_") for _, _, version in candidates],
            self.parameters,
        )
        output: list[RetrievedEvidence] = []
        for components in component_scores:
            span, document, version = candidates[components.index]
            score = components.normalized_score
            if score == 0:
                continue
            output.append(
                RetrievedEvidence(
                    span=span,
                    document=document,
                    version=version,
                    score=score,
                    query_coverage=components.query_coverage,
                    lexical_score=components.lexical_score,
                    character_score=components.character_score,
                    authority_bonus=components.authority_bonus,
                )
            )
        output.sort(
            key=lambda item: (
                -item.score,
                -item.query_coverage,
                item.version.source_hash,
                item.span.ordinal,
            )
        )
        return [item.model_copy(update={"rank": rank}) for rank, item in enumerate(output[:limit], start=1)]


LexicalRetriever = HybridLexicalRetriever
