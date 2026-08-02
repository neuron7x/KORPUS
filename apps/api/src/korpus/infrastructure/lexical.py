"""Deterministic lexical retrieval.

A keyword baseline exists before any dense retriever for two reasons: document
numbers, abbreviations and model designations are exactly what embeddings blur
(SYSTEM.md), and a deterministic baseline is the only thing a dense retriever can
later be measured against. It reads the query — the previous stub did not.
"""

from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from korpus.domain.models import AccessTier, EvidenceSpan, Query

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

# Ukrainian function words carry no discriminative power and would otherwise let an
# empty question match every document with a coverage score above the threshold.
_STOPWORD_SOURCE = (
    "і й та але або що як який яка яке які це цей ця ці той та те ті "
    "в у на до з із зі за від про для по при над під без чи не ні "
    "є бути був була було були а щоб якщо коли де куди хто чим ким "
    "the a an of to in on for and or is are be by with from at as"
)
STOPWORDS: frozenset[str] = frozenset(_STOPWORD_SOURCE.split(" "))


def normalize(text: str) -> list[str]:
    """Casefold, strip diacritics-insensitive noise, drop stopwords, keep order."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return [token for token in _TOKEN.findall(folded) if token not in STOPWORDS]


def coverage_score(query_tokens: list[str], document_tokens: list[str]) -> float:
    """Fraction of distinct query terms present in the document, in [0, 1].

    Deliberately not TF-IDF: this is a floor, and a floor whose behaviour can be
    predicted by a reviewer without running it.
    """
    if not query_tokens:
        return 0.0
    wanted = set(query_tokens)
    present = wanted & set(document_tokens)
    return len(present) / len(wanted)


class LexicalRetriever:
    """In-process lexical index over pre-chunked spans.

    Corpus filtering and tier filtering both happen before scoring, so material
    outside the principal's authorization is never ranked, logged or returned.
    """

    def __init__(self, spans: list[EvidenceSpan] | None = None) -> None:
        self._spans = list(spans or [])

    @property
    def size(self) -> int:
        return len(self._spans)

    def add(self, span: EvidenceSpan) -> None:
        self._spans.append(span)

    async def search(
        self,
        query: Query,
        allowed_tiers: frozenset[AccessTier],
        allowed_corpora: frozenset[UUID],
        limit: int = 8,
    ) -> list[EvidenceSpan]:
        tokens = normalize(query.text)
        results: list[tuple[float, str, EvidenceSpan]] = []

        for span in self._spans:
            if span.access_tier not in allowed_tiers:
                continue
            if span.corpus_id not in allowed_corpora:
                continue
            score = coverage_score(tokens, normalize(span.text))
            if score <= 0:
                continue
            results.append((score, str(span.chunk_id), span))

        results.sort(key=lambda item: (-item[0], item[1]))
        return [
            span.model_copy(update={"retrieval_score": score})
            for score, _, span in results[:limit]
        ]
