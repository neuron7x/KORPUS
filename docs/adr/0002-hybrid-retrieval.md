# ADR-0002: Hybrid retrieval with evidence gates

Status: accepted

## Decision

Combine lexical and dense retrieval, rank fusion, metadata filtering, reranking, and
claim-level citations. Generation is prohibited below the configured evidence gate.

## Rationale

Exact identifiers and statutory phrases need lexical search; paraphrased questions
benefit from embeddings. Neither score establishes source truth, so authority,
validity, review, and access are deterministic filters.

