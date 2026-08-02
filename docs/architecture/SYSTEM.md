# System architecture

## First principles

1. **Truth is a data-lifecycle property, not a prompt.** Authority, version, rights,
   and review state are modeled before embedding.
2. **Separate deterministic and probabilistic work.** Authorization, filtering,
   schema validation, revision precedence, and audit are code; semantic retrieval and
   synthesis may use models.
3. **Keep evidence inspectable.** Store immutable spans and page coordinates, not only
   vectors.
4. **Abstention is a successful result.** Lack of evidence is not an exception.
5. **Start as a modular monolith.** Split services only after measured scaling or
   isolation needs.
6. **Provider independence.** The domain depends on retrieval/generation ports, not an
   SDK.

## Context view

```text
User / Instructor / Reviewer
            │
        Web PWA
            │ HTTPS/OIDC
      API modular monolith
       ├── Identity & policy
       ├── Corpus lifecycle
       ├── Retrieval & reranking
       ├── Answer orchestration
       ├── Learning
       ├── Document drafts
       └── Audit & feedback
          │       │       │
     PostgreSQL  Object   Queue
      + pgvector storage  (Redis)
          │
  Provider adapters (OpenAI / local / other)
```

## Retrieval pipeline

1. Normalize query without changing intent.
2. Resolve user tier, role, selected corpus, locale, and requested platform.
3. Apply access and validity filters before retrieval.
4. Run lexical and dense retrieval in parallel.
5. Fuse ranks (RRF), deduplicate by canonical document/version, then rerank.
6. Enforce authority precedence and document supersession.
7. Return evidence spans with page/section coordinates and scores.
8. Apply answer policy. If insufficient, abstain or request clarification.
9. Generate a structured answer using only provided evidence.
10. Verify claim/citation coverage and policy before display.

Vector similarity alone never determines truth. Hybrid retrieval protects exact
terms, document numbers, abbreviations, and model identifiers that embeddings may
blur.

## Data stores

- PostgreSQL: canonical metadata, users, roles, review workflow, templates, curricula,
  answer records, and append-only audit references.
- pgvector: embeddings keyed to immutable chunks and embedding version.
- S3-compatible object storage: original files, extracted text, page images, signed
  review artifacts. Buckets are separated by access tier.
- Redis: short-lived jobs, rate limits, idempotency, and cache only; no source of truth.

## Deployment progression

1. Local Compose for development.
2. Single-region managed container platform with managed PostgreSQL/object storage.
3. Separate ingestion workers and restricted-corpus deployment when load or policy
   requires it.
4. Multi-region only after explicit data-residency and recovery requirements.

Kubernetes is not an MVP requirement. Operational complexity must follow measured
need.

## Model routing

- Router/extractor: small low-latency model or deterministic parser.
- Balanced answer generation: mid-tier model.
- Hard review/evaluation: quality model.
- Embeddings and reranker are independently versioned.

Current OpenAI defaults are configuration only: Luna/Terra/Sol roles respectively.
No route is promoted without task-specific cost, latency, and quality evaluation.

## Reliability

- idempotency keys on ingestion and draft creation;
- transactional outbox for async jobs;
- bounded retries with exponential backoff and jitter;
- dead-letter queue with replay tooling;
- readiness distinct from liveness;
- point-in-time database recovery and versioned object storage;
- restore drills, not backup-only confidence;
- degraded mode supports source browsing when generation is unavailable.

