# ADR-0005: Bounded database candidate retrieval

Status: accepted.

## Decision

Apply identity, corpus, classification, review and temporal predicates inside the database candidate query. Use SQLite FTS5 locally and PostgreSQL GIN/`tsvector` in controlled deployment. Rerank at most a configured candidate budget in application memory.

## Rationale

The previous implementation loaded every accessible span and scored it in Python. This was semantically safer than loading restricted rows, but had O(N) query cost and an unbounded memory surface. The new path keeps access filtering before text materialization and bounds application work.

## Consequences

- lexical index becomes derived infrastructure;
- candidate recall must be evaluated separately from reranker quality;
- dense retrieval requires a new adapter and matched evaluation, not an inline library swap;
- historical supersession must be represented in the candidate SQL, not inferred only from returned candidates.
