# KORPUS v3.0.0

Evidence-bound knowledge, training and administrative platform for controlled Ukrainian document corpora.

KORPUS is not an autonomous operational decision-maker and does not treat an LLM as an authority. Its trust kernel ingests immutable sources, applies server-derived access policy before retrieval, selects temporally valid approved versions, emits exact extractive claims with content-bound citations, abstains under insufficient support, and records every decision in a recoverable tamper-evident audit ledger.

## Implemented trust path

```text
verified identity
  -> corpus / tier / classification policy
  -> SQL temporal and review predicates
  -> bounded database candidate index
       SQLite FTS5 | PostgreSQL GIN tsvector
  -> deterministic BM25 + character reranking
  -> calibrated claim-support gate
  -> exact extractive claim + citation offsets/hash
  -> audit transaction + anchor outbox
  -> external HMAC checkpoint
```

## What changed in v3

- retrieval is a calibrated convex utility with explicit lexical, semantic, coverage, authority, phrase and temporal weights;
- PostgreSQL FORCE RLS is an independent database barrier beneath application ABAC;
- pgvector candidates fuse with bounded lexical candidates before deterministic reranking;
- identity/release/config-scoped cache, admission control and circuit breakers bound operational work;
- OIDC uses cached JWKS, mandatory `kid`, issuer/audience checks and asymmetric algorithm pinning;
- S3 writes are content-addressed, checksummed and optionally governance-retained;
- OpenTelemetry and Prometheus expose low-cardinality operational evidence without source/query identifiers;
- audit checkpoints can be delivered through an idempotent remote monotonic HMAC anchor;
- an explicit operational gate composes eval, mutation, migration and scale evidence without claiming production authorization;
- fourteen critical first-order mutants must all be killed before release.

## Executable assurance gates

```bash
make assurance
```

This runs repository validation, Python compilation, branch-aware tests, frozen evaluation, critical mutation testing, clean-database migration parity, local scale probe and web build. Ruff, mypy, dependency audit, secret scan, SBOM, containers and PostgreSQL integration are separate GitLab gates.

Successful release evidence is promoted with `make snapshot` into content-hashed files under `reports/`. Passing these gates proves only the encoded predicates. It does not prove corpus rights, official authority, military security authorization, OCR fidelity on real documents, production SLA or accreditation.

## Repository map

```text
apps/api/                  FastAPI modular monolith and trust kernel
apps/web/                  dependency-free offline-capable PWA
packages/contracts/        versioned public boundary schemas
infra/                     local infrastructure and observability
scripts/                   assurance, migration, eval and packaging tools
evals/                     frozen scenario and adversarial fixtures
docs/assurance/            value function, verification lattice, assurance case
docs/research/             primary-source research provenance
docs/architecture/         system topology, security and data model
agents/                    Codex / Claude Code execution contracts
.gitlab/                   CI, CODEOWNERS and MR controls
```

## Local start

Requirements: Python 3.12+, Node 22+.

```bash
cp .env.example .env
make api-install
make bootstrap
make assurance
make api-run
```

In another terminal:

```bash
make web-install
make web-run
```

API: `http://127.0.0.1:8000`

Web: `http://127.0.0.1:3000`
OpenAPI: `http://127.0.0.1:8000/docs`

The local identity is configuration-derived. Request bodies cannot select clearance, roles or corpus assignment.

## Core killable invariants

1. Inaccessible text never enters ranking, answer, citation, metric or release identity.
2. A quarantined, rejected, future, expired, rescinded or actively superseded version cannot answer.
3. Every claim equals a cited substring and verifies by exact offsets and SHA-256.
4. Retrieved text is data and cannot become a control instruction.
5. Missing or uncalibrated support produces a named abstention.
6. Metadata, versions, spans and audit event commit or roll back together.
7. Audit ordering, predecessor relation, HMAC, database head and external anchor agree.
8. Candidate work is bounded before application reranking.
9. Fixed code, corpus release, calibration and query produce the same semantic output.
10. Agent output cannot merge without independent verification and protected GitLab gates.

## Deployment modes

- `local`: SQLite FTS5, local immutable object store, development identity.
- `controlled`: migration-managed PostgreSQL, OIDC/JWKS, external object lock and restricted egress.
- `isolated`: private registries and model gateway, dedicated runners, no public-provider data path.

Read first:

- `docs/assurance/FIRST_PRINCIPLES.md`
- `docs/assurance/TEST_STRATEGY.md`
- `docs/assurance/ASSURANCE_CASE.md`
- `docs/research/RESEARCH_PROVENANCE_2026.md`
- `docs/assurance/ITERATION_LEDGER_V3.md`
- `docs/protocols/INTEGRATIONS_V3.md`
- `docs/architecture/SYSTEM_V3.md`
- `AGENTS.md`
