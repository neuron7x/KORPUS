# KORPUS v4.0.0

Evidence-bound knowledge, training and administrative platform for controlled Ukrainian document corpora.

KORPUS is not an autonomous operational decision-maker and does not treat an LLM as authority. Its trust kernel ingests immutable sources, derives identity and access server-side, filters inaccessible data before retrieval, selects temporally valid approved versions, emits exact extractive claims with content-bound citations, abstains when support is insufficient, and records decisions in a recoverable tamper-evident audit ledger.

## Implemented trust path

```text
verified OIDC identity
  -> application ABAC + PostgreSQL FORCE RLS
  -> temporal/current/review predicates
  -> bounded lexical + optional calibrated semantic candidates
  -> deterministic reranking and support gate
  -> extractive claim + offsets/hash citation
  -> database transaction + durable anchor outbox
  -> authenticated monotonic remote checkpoint
```

## Infrastructure topology

```text
127.0.0.1:3000
      |
non-root nginx/PWA -- internal edge -- API
                                      |-- internal backend --> PostgreSQL/pgvector
                                      |                    --> S3/MinIO object lock
                                      |                    --> OTel collector
                                      `-- dedicated egress --> OIDC / embeddings / audit anchor
```

Only the web proxy publishes a loopback host port. Backend networks are internal. Only the API joins the egress network.

## What changed in v4

- Compose services are wired into runtime configuration and health-dependent startup.
- Alembic migration and non-superuser role preparation precede API startup.
- PostgreSQL `FORCE ROW LEVEL SECURITY` covers documents, versions, spans and embeddings.
- MinIO uses a dedicated prefix-scoped application identity without object deletion rights.
- Controlled S3 readiness verifies bucket versioning and object-lock capability.
- Audit commit and remote anchoring are separated by a durable transactional outbox.
- Readiness uses bounded head/history/outbox checks instead of scanning the full ledger.
- PostgreSQL backup streams directly from `pg_dump` into AES-256-GCM; no plaintext backup file is created.
- Backup manifest v4 is HMAC-authenticated and binds filename, hashes, byte counts, cipher and key ID.
- Restore rejects manifest tampering, wrong key ID, wrong hashes/sizes and wrong Alembic head.
- GitLab builds OCI archives with rootless BuildKit and requires dependency, secret, IaC and container scans plus SBOMs.
- Packaging starts from committed `git archive HEAD` and rejects stale source-mismatched assurance evidence.
- SQLite uses connection-per-unit-of-work semantics to prevent cross-lifecycle DB-handle leakage.

## Executable gates

```bash
make assurance
```

Local evidence for this release:

- 125 tests collected: 124 PASS, 1 live-PostgreSQL SKIP, 0 failures;
- combined coverage 82.34%; statement coverage 86.72%; branch coverage 64.78%;
- adversarial evaluation 30/30 PASS;
- critical mutations 14/14 killed;
- clean Alembic migration parity PASS;
- local bounded scale probe PASS;
- web validation/typecheck/build PASS;
- repository and infrastructure static contracts PASS.

These gates prove only encoded predicates in the supplied environment. They do not prove document rights, official authority, real-corpus OCR accuracy, production SLA, penetration resistance or state/military authorization.

## Local start

Requirements: Python 3.12+, Node 22+, Docker Compose for the integrated infrastructure profile.

```bash
cp .env.example .env
make infra-secrets
make infra-up
```

Web: `http://127.0.0.1:3000`

API through proxy: `http://127.0.0.1:3000/api`

Direct developer API: `make api-run`

Local development without Docker:

```bash
make api-install
make bootstrap
make api-test
make web-install
make web-build
```

## Repository map

```text
apps/api/                  FastAPI trust kernel and adapters
apps/web/                  dependency-free offline-capable PWA
packages/contracts/        versioned public schemas
infra/                     MinIO policies, telemetry and secrets contract
scripts/                   migration, assurance, backup, restore and packaging tools
evals/                     frozen adversarial fixtures
reports/                   content-hashed release evidence
docs/architecture/         system and security topology
docs/assurance/            falsification strategy and audit ledger
agents/                    Codex / Claude Code worktree contracts
.gitlab/                   CI, CODEOWNERS and merge controls
```

## Core killable invariants

1. Inaccessible text never enters candidate ranking, answers, citations, metrics or release identity.
2. Quarantined, rejected, future, expired, rescinded or superseded versions cannot answer outside their valid interval.
3. Every claim equals a cited substring and verifies by offsets, quote hash and source hash.
4. Retrieved text is data and cannot become a control instruction.
5. Missing or uncalibrated evidence produces an explicit abstention.
6. Metadata, versions, spans and audit events commit or roll back atomically.
7. Audit event chain, database head, outbox and remote anchor agree or readiness fails.
8. Candidate work is bounded before application reranking.
9. Fixed code, corpus release, calibration and query produce deterministic semantic output.
10. Backup recovery requires authenticated metadata, exact hashes/sizes, transactional restore, schema parity and RLS isolation.
11. Release evidence must match committed `HEAD`; mutable working-tree files cannot enter source packages implicitly.
12. Agent output cannot merge without independent review and protected GitLab gates.

## Read first

- `docs/architecture/SYSTEM_V4.md`
- `docs/assurance/INFRASTRUCTURE_AUDIT_V4.md`
- `docs/assurance/FIRST_PRINCIPLES.md`
- `docs/assurance/TEST_STRATEGY.md`
- `docs/assurance/ASSURANCE_CASE.md`
- `docs/runbooks/BACKUP_RESTORE.md`
- `docs/runbooks/OPERATIONS.md`
- `AGENTS.md`
