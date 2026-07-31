from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date

from korpus.application.ports import Repository
from korpus.domain.models import Identity, RetrievedEvidence

TOKEN_PATTERN = re.compile(r"[\w'’\-]{2,}", re.UNICODE)
STOP_WORDS = {
    "але", "без", "був", "була", "були", "для", "його", "коли", "про", "та", "так", "це", "що",
    "the", "and", "for", "from", "that", "this", "with",
}


def tokenize(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN_PATTERN.findall(text) if token.casefold() not in STOP_WORDS]


class LexicalRetriever:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def search(
        self,
        identity: Identity,
        text: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int = 8,
    ) -> list[RetrievedEvidence]:
        query_tokens = tokenize(text)
        if not query_tokens:
            return []
        candidates = self.repository.list_retrievable_spans(identity, corpus_ids, as_of)
        if not candidates:
            return []

        docs = [tokenize(span.text) for span, _, _ in candidates]
        document_frequency: Counter[str] = Counter()
        for tokens in docs:
            document_frequency.update(set(tokens))
        avg_len = sum(len(tokens) for tokens in docs) / max(len(docs), 1)
        n_docs = len(docs)
        query_set = set(query_tokens)
        scored: list[RetrievedEvidence] = []

        for (span, document, version), tokens in zip(candidates, docs, strict=True):
            if not tokens:
                continue
            frequencies = Counter(tokens)
            bm25 = 0.0
            for term in query_set:
                frequency = frequencies.get(term, 0)
                if frequency == 0:
                    continue
                df = document_frequency[term]
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / max(avg_len, 1))
                bm25 += idf * (frequency * 2.5) / denominator
            coverage = len(query_set.intersection(tokens)) / len(query_set)
            phrase_bonus = 0.15 if text.casefold() in span.text.casefold() else 0.0
            authority_bonus = 0.08 if version.authority.value.startswith("official_") else 0.0
            normalized = min(1.0, (1 - math.exp(-bm25 / 3)) * 0.70 + coverage * 0.22 + phrase_bonus + authority_bonus)
            if normalized > 0:
                scored.append(
                    RetrievedEvidence(
                        span=span,
                        document=document,
                        version=version,
                        score=normalized,
                        query_coverage=coverage,
                    )
                )
        scored.sort(key=lambda item: (item.score, item.query_coverage), reverse=True)
        return scored[:limit]
