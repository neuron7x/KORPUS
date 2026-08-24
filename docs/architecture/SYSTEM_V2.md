# System architecture v2

> **HISTORICAL SNAPSHOT — NOT CURRENT SSOT.** Current architecture: `SYSTEM.md`.

## Deployment topology

```text
OIDC / JWKS
    |
Policy decision point
    |
SQL access + temporal predicates
    |
Database candidate index (SQLite FTS5 / PostgreSQL GIN tsvector)
    |
Bounded deterministic BM25 + character reranker
    |
Claim-support and abstention gate
    |
Exact extractive claims + immutable citations
    |
Audit transaction + anchor outbox -> external HMAC anchor
```

## Why a modular monolith remains correct

Authorization, temporal version selection, evidence construction and audit are one trust transaction. Splitting them into network services before pressure is measured creates more failure modes: stale policy caches, cross-service race conditions, partial audit, distributed tracing gaps and broader secret distribution. Ports isolate storage, retrieval and object-store adapters so extraction remains possible after contract and load evidence exists.

## Scale path

1. Local/reference: SQLite + FTS5, bounded reranker, local immutable objects.
2. Controlled single-region: PostgreSQL GIN index, object lock, OIDC, queue-backed ingestion, external anchor.
3. High-scale: dedicated lexical/vector candidate service behind the same `Retriever` contract, with ABAC enforced in or before the index.
4. Isolated: local model gateway and registries, no public provider egress.

The current code implements stages 1 and the PostgreSQL lexical path for stage 2. Dense retrieval is deliberately absent until a corpus-specific benchmark proves incremental recall after matched false-access and latency constraints.

## Synchronization model

- GitLab protected `main` is code SSOT.
- SQL is metadata/review/audit SSOT.
- content-addressed object storage is raw-source SSOT.
- search indexes are derived and rebuildable.
- local worktrees are disposable.
- Codex and Claude Code never share a working tree or direct-write protected branches.

No bidirectional file synchronization is used as a consistency mechanism.
