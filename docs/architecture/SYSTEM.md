# System architecture

## Trust path

```text
verified identity
  -> policy decision point
  -> authorized corpus intersection
  -> approved/current version filter
  -> lexical retrieval and ranking
  -> evidence sufficiency gate
  -> extractive claim construction
  -> immutable citation binding
  -> hash-chained audit
```

The current executable implementation is a modular monolith. This is deliberate: authorization, retrieval, version validity, answer construction, and audit share transactional invariants that are easier to prove inside one process. Service extraction is allowed only after measured scaling pressure and contract tests exist.

## Source of truth

- GitLab protected `main`: code and contracts.
- SQL database: metadata, versions, spans, review state, audit chain.
- Object store: immutable source bytes addressed by SHA-256.
- Corpus release identifier: digest of all version identifiers, hashes, and review states.
- CI artifacts: build outputs, SBOM, coverage and evaluation reports.

Local worktrees are disposable and never authoritative.

## Boundaries

1. API boundary: validated Pydantic and JSON Schema contracts.
2. Identity boundary: signed JWT or fixed local identity; no client-selected clearance.
3. Corpus boundary: corpus assignment and access tier enforced before ranking.
4. Source boundary: uploads enter quarantine and cannot answer until reviewed.
5. Generation boundary: current implementation is extractive; external LLM providers are absent by design.
6. Audit boundary: HMAC hash chain detects modification but does not replace WORM/remote anchoring.

## Production extensions

A controlled deployment should add PostgreSQL row-level security, S3-compatible object lock, OIDC/JWKS key rotation, malware/CDR pipeline, queue-backed ingestion, OpenSearch/pgvector hybrid retrieval, external timestamp anchoring, and a separately authorized model gateway.
