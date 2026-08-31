from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from korpus.application.authority_policy import validate_authority_priors
from korpus.application.ports import Repository, Retriever
from korpus.application.runtime_contracts import validate_retrieval_limits
from korpus.domain.models import AuthorityClass, Identity, RetrievedEvidence


class RetrievalDeadlineExceeded(TimeoutError):
    """Raised when the deterministic retrieval budget is exhausted."""


class RetrievalUnavailable(RuntimeError):
    """Raised when a required retrieval dependency is unavailable."""


from korpus.application.retrieval_math import (
    DEFAULT_BM25_PARAMETERS,
    DEFAULT_RETRIEVAL_WEIGHTS,
    BM25Parameters,
    RetrievalWeights,
    character_ngrams,
    jaccard,
)
from korpus.application.retrieval_math import (
    ScoredCandidate as ScoredCandidate,
)
from korpus.application.retrieval_math import (
    _ukrainian_stem as _ukrainian_stem,
)
from korpus.application.retrieval_math import (
    candidate_terms as candidate_terms,
)
from korpus.application.retrieval_math import (
    normalize_text as normalize_text,
)
from korpus.application.retrieval_math import (
    raw_tokens as raw_tokens,
)
from korpus.application.retrieval_math import (
    score_candidates as score_candidates,
)
from korpus.application.retrieval_math import (
    tokenize as tokenize,
)

AUTHORITY_PRIOR: dict[AuthorityClass, float] = {
    AuthorityClass.OFFICIAL_UA: 1.00,
    AuthorityClass.OFFICIAL_ALLIED: 0.92,
    AuthorityClass.MANUFACTURER: 0.78,
    AuthorityClass.APPROVED_TRAINING: 0.74,
    AuthorityClass.ANALYTICAL: 0.46,
    AuthorityClass.HISTORICAL: 0.30,
    AuthorityClass.ADVERSARY: 0.00,
    AuthorityClass.UNKNOWN: 0.00,
}


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
    subject_documents: frozenset[str] = frozenset(),
) -> list[RetrievedEvidence]:
    """Maximal-marginal-relevance selection, ordered by authority class first.

    Authority used to be one term of a convex sum with weight 0.14, which makes it a
    quantity that similarity can outbid: the prior gap between OFFICIAL_UA and
    ANALYTICAL is 0.0756, so a well-matched analytical passage outranked the order it
    contradicts. Rank is now lexicographic — authority class first, marginal relevance
    only as a tie-break inside the class — so no amount of lexical similarity promotes
    a weaker source above a stronger one.

    Оголошений предмет стоїть ЩЕ ВИЩЕ за тим самим міркуванням: стаття з обов'язками
    ролі не повторює її назви, тож лексично програє довгому статуту, що згадав роль
    мимохідь. Виміряно 0 правильних зі 101. Це не вага, яку схожість може перебити, а
    клас: документ, чий ОГОЛОШЕНИЙ предмет збігся з предметом питання, не «доречніший»
    — він про того, кого спитали.
    """

    if not 0 <= diversity_lambda <= 1:
        raise ValueError("diversity_lambda must be in [0, 1]")
    if limit < 1 or per_version_cap < 1:
        raise ValueError("limits must be positive")
    priors = authority_priors or AUTHORITY_PRIOR
    selected: list[RetrievedEvidence] = []
    remaining = list(ranked)
    version_counts: defaultdict[str, int] = defaultdict(int)
    grams = (
        {str(item.span.id): character_ngrams(item.span.text) for item in ranked}
        if diversity_lambda < 1.0
        else {}
    )
    while remaining and len(selected) < limit:
        admissible = [
            item for item in remaining if version_counts[str(item.version.id)] < per_version_cap
        ]
        if not admissible:
            break

        def utility(item: RetrievedEvidence) -> tuple[float, float, float, float, str, int]:
            if diversity_lambda == 1.0:
                mmr = item.score
            else:
                redundancy = max(
                    (
                        jaccard(grams[str(item.span.id)], grams[str(other.span.id)])
                        for other in selected
                    ),
                    default=0.0,
                )
                mmr = diversity_lambda * item.score - (1 - diversity_lambda) * redundancy
            return (
                1.0 if str(item.document.id) in subject_documents else 0.0,
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
        contextual_projection_enabled: bool = False,
        approved_aliases: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        validate_retrieval_limits(candidate_budget, timeout_ms)
        self.repository = repository
        self.parameters = parameters
        self.candidate_budget = candidate_budget
        self.weights = weights
        self.diversity_lambda = diversity_lambda
        self.per_version_cap = per_version_cap
        self.timeout_ms = timeout_ms
        self.semantic_source = semantic_source
        self.authority_priors = dict(authority_priors or AUTHORITY_PRIOR)
        self.contextual_projection_enabled = contextual_projection_enabled
        self.approved_aliases = dict(approved_aliases or {})
        validate_authority_priors(self.authority_priors)

    def semantic_available(self) -> bool:
        return self.semantic_source is not None and self.weights.semantic > 0

    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int = 8,
    ) -> list[RetrievedEvidence]:
        return self._search(identity, text, corpus_ids, as_of, limit, semantic_enabled=None)

    def search_with_semantic(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int = 8,
        *,
        semantic_enabled: bool,
    ) -> list[RetrievedEvidence]:
        if semantic_enabled and not self.semantic_available():
            raise RetrievalUnavailable("semantic retrieval is not admitted or available")
        return self._search(
            identity, text, corpus_ids, as_of, limit, semantic_enabled=semantic_enabled
        )

    def _search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int,
        *,
        semantic_enabled: bool | None,
    ) -> list[RetrievedEvidence]:
        from korpus.application.retrieval_execution import (
            ExecutionDeadlineExceeded,
            ExecutionUnavailable,
            execute_hybrid_search,
        )

        try:
            return execute_hybrid_search(
                repository=self.repository,
                parameters=self.parameters,
                candidate_budget=self.candidate_budget,
                weights=self.weights,
                timeout_ms=self.timeout_ms,
                semantic_source=self.semantic_source,
                semantic_available=self.semantic_available(),
                authority_priors=self.authority_priors,
                contextual_projection_enabled=self.contextual_projection_enabled,
                approved_aliases=self.approved_aliases,
                identity=identity,
                text=text,
                corpus_ids=corpus_ids,
                as_of=as_of,
                limit=limit,
                semantic_enabled=semantic_enabled,
                temporal_relevance=_temporal_relevance,
                diversify=diversify_evidence,
                diversity_lambda=self.diversity_lambda,
                per_version_cap=self.per_version_cap,
            )
        except ExecutionDeadlineExceeded as exc:
            raise RetrievalDeadlineExceeded(str(exc)) from exc
        except ExecutionUnavailable as exc:
            raise RetrievalUnavailable(str(exc)) from exc


LexicalRetriever = HybridLexicalRetriever
