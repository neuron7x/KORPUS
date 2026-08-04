from __future__ import annotations

import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from korpus.application.ports import Repository, Retriever
from korpus.domain.models import AuthorityClass, Identity, RetrievedEvidence

TOKEN_PATTERN = re.compile(r"[\w'’\-]{2,}", re.UNICODE)
STOP_WORDS = {
    "але", "без", "був", "була", "були", "для", "його", "коли", "про", "та", "так", "це", "що",
    "який", "яка", "яке", "які", "має", "мати", "the", "and", "for", "from", "that", "this", "with",
}


class RetrievalDeadlineExceeded(TimeoutError):
    """Raised when the deterministic retrieval budget is exhausted."""


class RetrievalUnavailable(RuntimeError):
    """Raised when a required retrieval dependency is unavailable."""


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


UKRAINIAN_SUFFIXES = tuple(sorted({
    "ування", "ювання", "овувати", "ювати", "еві", "ові", "ями", "ами", "ого", "ому",
    "ими", "ій", "ою", "ею", "ення", "ання", "яння", "ість", "остей", "ати", "ити",
    "увати", "ений", "аний", "альна", "альне", "альний", "альні", "у", "ю",
    "а", "я", "і", "и", "е", "є", "ом", "ем", "ів", "їв", "ах", "ях", "ам", "ям",
}, key=len, reverse=True))


def _ukrainian_stem(token: str) -> str:
    if len(token) < 5 or not any("а" <= char <= "я" or char in "іїєґ" for char in token):
        return token
    for suffix in UKRAINIAN_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[:-len(suffix)]
    return token


def raw_tokens(text: str) -> list[str]:
    return [
        token for token in TOKEN_PATTERN.findall(normalize_text(text)) if token not in STOP_WORDS
    ]


def tokenize(text: str) -> list[str]:
    return [_ukrainian_stem(token) for token in raw_tokens(text)]


def candidate_terms(text: str) -> list[tuple[str, bool]]:
    """Return exact and Ukrainian stem-prefix terms for candidate generation."""
    result: list[tuple[str, bool]] = []
    seen: set[tuple[str, bool]] = set()
    for token in raw_tokens(text):
        for value in ((token, False), (_ukrainian_stem(token), True)):
            if len(value[0]) >= 2 and value not in seen:
                seen.add(value)
                result.append(value)
    return result


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

    def __post_init__(self) -> None:
        if not 0.1 <= self.k1 <= 4.0:
            raise ValueError("BM25 k1 must be in [0.1, 4.0]")
        if not 0.0 <= self.b <= 1.0:
            raise ValueError("BM25 b must be in [0, 1]")


@dataclass(frozen=True)
class RetrievalWeights:
    """Auditable convex utility function for evidence ranking.

    Every component is normalized to [0, 1]. The weights form a convex
    combination, so score meaning does not silently change when components are
    added. Values are configuration/calibration inputs, not hidden constants.
    """

    lexical: float = 0.42
    semantic: float = 0.00
    query_coverage: float = 0.24
    character: float = 0.10
    authority: float = 0.14
    phrase: float = 0.06
    temporal: float = 0.04

    def __post_init__(self) -> None:
        values = self.as_tuple()
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("retrieval weights must be in [0, 1]")
        if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("retrieval weights must sum to 1")

    def as_tuple(self) -> tuple[float, ...]:
        return (
            self.lexical,
            self.semantic,
            self.query_coverage,
            self.character,
            self.authority,
            self.phrase,
            self.temporal,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "lexical": self.lexical,
            "semantic": self.semantic,
            "query_coverage": self.query_coverage,
            "character": self.character,
            "authority": self.authority,
            "phrase": self.phrase,
            "temporal": self.temporal,
        }


# Both dataclasses are frozen with float-only fields, so one shared instance is
# indistinguishable from a fresh one per call. Module-level singletons keep the
# calibrated defaults in a single named place instead of re-running __post_init__
# validation on every call.
DEFAULT_BM25_PARAMETERS = BM25Parameters()
DEFAULT_RETRIEVAL_WEIGHTS = RetrievalWeights()

AUTHORITY_PRIOR: dict[AuthorityClass, float] = {
    AuthorityClass.OFFICIAL_UA: 1.00,
    AuthorityClass.OFFICIAL_ALLIED: 0.92,
    AuthorityClass.MANUFACTURER: 0.78,
    AuthorityClass.APPROVED_TRAINING: 0.74,
    AuthorityClass.ANALYTICAL: 0.46,
    AuthorityClass.HISTORICAL: 0.30,
    AuthorityClass.UNKNOWN: 0.00,
}


@dataclass(frozen=True)
class ScoredCandidate:
    index: int
    lexical_score: float
    semantic_score: float
    query_coverage: float
    character_score: float
    authority_score: float
    phrase_score: float
    temporal_score: float
    weights: RetrievalWeights

    @property
    def lexical_normalized(self) -> float:
        return 1 - math.exp(-self.lexical_score / 3)

    @property
    def normalized_score(self) -> float:
        components = (
            self.lexical_normalized,
            self.semantic_score,
            self.query_coverage,
            self.character_score,
            self.authority_score,
            self.phrase_score,
            self.temporal_score,
        )
        # as_tuple() and components are both the same fixed seven axes, in the same
        # order, so strict=True can never fire here.
        combined = sum(
            weight * value
            for weight, value in zip(self.weights.as_tuple(), components, strict=True)
        )
        return min(1.0, max(0.0, combined))


def score_candidates(
    query: str,
    texts: list[str],
    official: list[bool] | None = None,
    parameters: BM25Parameters = DEFAULT_BM25_PARAMETERS,
    *,
    authority_scores: list[float] | None = None,
    semantic_scores: list[float] | None = None,
    temporal_scores: list[float] | None = None,
    weights: RetrievalWeights = DEFAULT_RETRIEVAL_WEIGHTS,
) -> list[ScoredCandidate]:
    if official is None:
        official = [False] * len(texts)
    if len(texts) != len(official):
        raise ValueError("texts and authority flags must have equal length")
    if authority_scores is None:
        authority_scores = [1.0 if value else 0.0 for value in official]
    if semantic_scores is None:
        semantic_scores = [0.0] * len(texts)
    if temporal_scores is None:
        temporal_scores = [0.0] * len(texts)
    if (
        len(authority_scores) != len(texts)
        or len(semantic_scores) != len(texts)
        or len(temporal_scores) != len(texts)
    ):
        raise ValueError("component arrays must have equal length")
    if any(
        not 0 <= value <= 1
        for value in authority_scores + semantic_scores + temporal_scores
    ):
        raise ValueError("normalized component scores must be in [0, 1]")

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
    normalized_query = normalize_text(query)
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
        phrase_score = 1.0 if normalized_query in normalize_text(texts[index]) else 0.0
        scored.append(
            ScoredCandidate(
                index=index,
                lexical_score=bm25,
                semantic_score=semantic_scores[index],
                query_coverage=query_coverage,
                character_score=character_score,
                authority_score=authority_scores[index],
                phrase_score=phrase_score,
                temporal_score=temporal_scores[index],
                weights=weights,
            )
        )
    return scored


def _temporal_relevance(
    as_of: date, publication_date: date | None, effective_from: date | None
) -> float:
    reference = effective_from or publication_date
    if reference is None or reference > as_of:
        return 0.0
    age_days = max(0, (as_of - reference).days)
    # Recency is a weak ranking signal, never an authority decision.
    # Half-life: ~4 years; floor 0.25.
    return max(0.25, 1.0 / (1.0 + age_days / 1461.0))


def diversify_evidence(
    ranked: list[RetrievedEvidence],
    *,
    limit: int,
    diversity_lambda: float = 0.82,
    per_version_cap: int = 1,
    authority_priors: dict[AuthorityClass, float] | None = None,
) -> list[RetrievedEvidence]:
    """Maximal-marginal-relevance selection, ordered by authority class first.

    Authority used to be one term of a convex sum with weight 0.14, which makes it a
    quantity that similarity can outbid: the prior gap between OFFICIAL_UA and
    ANALYTICAL is 0.0756, so a well-matched analytical passage outranked the order it
    contradicts. Rank is now lexicographic — authority class first, marginal relevance
    only as a tie-break inside the class — so no amount of lexical similarity promotes
    a weaker source above a stronger one.
    """

    if not 0 <= diversity_lambda <= 1:
        raise ValueError("diversity_lambda must be in [0, 1]")
    if limit < 1 or per_version_cap < 1:
        raise ValueError("limits must be positive")
    priors = authority_priors or AUTHORITY_PRIOR
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

        def utility(item: RetrievedEvidence) -> tuple[float, float, float, str, int]:
            redundancy = max(
                (
                    jaccard(grams[str(item.span.id)], grams[str(other.span.id)])
                    for other in selected
                ),
                default=0.0,
            )
            mmr = diversity_lambda * item.score - (1 - diversity_lambda) * redundancy
            return (
                priors[item.version.authority],
                mmr,
                item.score,
                item.version.source_hash,
                -item.span.ordinal,
            )

        winner = max(admissible, key=utility)
        selected.append(winner)
        version_counts[str(winner.version.id)] += 1
        remaining.remove(winner)
    return [item.model_copy(update={"rank": rank}) for rank, item in enumerate(selected, start=1)]


class HybridLexicalRetriever(Retriever):
    """Deterministic candidate retrieval + calibrated convex reranking + MMR."""

    def __init__(
        self,
        repository: Repository,
        parameters: BM25Parameters = DEFAULT_BM25_PARAMETERS,
        candidate_budget: int = 256,
        *,
        weights: RetrievalWeights = DEFAULT_RETRIEVAL_WEIGHTS,
        diversity_lambda: float = 0.82,
        per_version_cap: int = 1,
        timeout_ms: int = 1200,
        semantic_source: Any | None = None,
        authority_priors: dict[AuthorityClass, float] | None = None,
    ) -> None:
        if candidate_budget < 8:
            raise ValueError("candidate_budget must be at least 8")
        if timeout_ms < 10:
            raise ValueError("timeout_ms must be at least 10")
        self.repository = repository
        self.parameters = parameters
        self.candidate_budget = candidate_budget
        self.weights = weights
        self.diversity_lambda = diversity_lambda
        self.per_version_cap = per_version_cap
        self.timeout_ms = timeout_ms
        self.semantic_source = semantic_source
        self.authority_priors = dict(authority_priors or AUTHORITY_PRIOR)
        if set(self.authority_priors) != set(AuthorityClass):
            raise ValueError("authority priors must cover every AuthorityClass")
        if any(not 0 <= value <= 1 for value in self.authority_priors.values()):
            raise ValueError("authority priors must be in [0, 1]")

    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int = 8,
    ) -> list[RetrievedEvidence]:
        started = time.monotonic()
        candidates = self.repository.search_retrievable_spans(
            identity, corpus_ids, as_of, text, self.candidate_budget
        )
        semantic_by_span: dict[str, float] = {}
        if self.semantic_source is not None and self.weights.semantic > 0:
            try:
                semantic_hits = self.semantic_source.search(
                    identity, text, corpus_ids, as_of, self.candidate_budget
                )
            except Exception as exc:
                raise RetrievalUnavailable("required semantic retrieval is unavailable") from exc
            semantic_by_span = {str(span_id): score for span_id, score in semantic_hits}
            missing_ids = [
                span_id
                for span_id, _ in semantic_hits
                if str(span_id) not in {str(span.id) for span, _, _ in candidates}
            ]
            if missing_ids:
                candidates.extend(
                    self.repository.get_retrievable_spans_by_ids(
                        identity, corpus_ids, as_of, missing_ids
                    )
                )
        if (time.monotonic() - started) * 1000 > self.timeout_ms:
            raise RetrievalDeadlineExceeded("candidate retrieval exceeded deadline")
        if not candidates:
            return []
        # Preserve first occurrence while fusing lexical and semantic candidates.
        candidates = list({str(item[0].id): item for item in candidates}.values())
        component_scores = score_candidates(
            text,
            [span.text for span, _, _ in candidates],
            [version.authority.value.startswith("official_") for _, _, version in candidates],
            self.parameters,
            authority_scores=[
                self.authority_priors[version.authority] for _, _, version in candidates
            ],
            semantic_scores=[semantic_by_span.get(str(span.id), 0.0) for span, _, _ in candidates],
            temporal_scores=[
                _temporal_relevance(as_of, version.publication_date, version.effective_from)
                for _, _, version in candidates
            ],
            weights=self.weights,
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
                    authority_bonus=components.authority_score,
                )
            )
        output.sort(
            key=lambda item: (
                -self.authority_priors[item.version.authority],
                -item.score,
                -item.query_coverage,
                item.version.source_hash,
                item.span.ordinal,
            )
        )
        if (time.monotonic() - started) * 1000 > self.timeout_ms:
            raise RetrievalDeadlineExceeded("reranking exceeded deadline")
        return diversify_evidence(
            output,
            limit=limit,
            diversity_lambda=self.diversity_lambda,
            per_version_cap=self.per_version_cap,
            authority_priors=self.authority_priors,
        )


LexicalRetriever = HybridLexicalRetriever
