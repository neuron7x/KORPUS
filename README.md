# KORPUS

Evidence-bound knowledge, training, and administrative platform for controlled Ukrainian document corpora.

KORPUS is not an autonomous operational decision-maker. It is a fail-closed document system that:

- ingests PDF, text, Markdown, JSON, and HTML documents;
- preserves source hashes and immutable document versions;
- requires review before a source becomes answerable;
- derives authorization from a verified server-side identity;
- filters access before retrieval;
- produces extractive, claim-to-span answers with immutable citations;
- records actions in a tamper-evident hash-chained audit ledger;
- supports frozen evaluations, adversarial tests, GitLab CI/CD, and isolated agent worktrees.

## Verified executable scope

The repository contains a working vertical slice, not a claim of formal state authorization:

1. authenticated identity;
2. ABAC policy decision;
3. secure ingestion and optional OCR fallback;
4. document/version/review lifecycle;
5. approved-only, access-filtered lexical retrieval;
6. evidence-bound extractive answers or explicit abstention;
7. persistent audit chain;
8. API, PWA, tests, evaluation runner, Docker, and GitLab pipeline.

The following remain deployment-specific and cannot be completed by source code alone: corpus rights, official reviewer appointments, data classification, security profile, independent penetration test, accreditation/authorization, production secrets, and operational ownership.

## Repository map

```text
apps/api/                  FastAPI modular monolith
apps/web/                  Dependency-free offline-capable PWA
packages/contracts/        Versioned boundary schemas
infra/                     Docker, OpenTelemetry, deployment profiles
scripts/                   Bootstrap, eval, worktree and validation tools
evals/                     Frozen functional and adversarial fixtures
docs/                      Architecture, governance, protocols and runbooks
agents/                    Codex / Claude Code execution contracts
.gitlab/                   CODEOWNERS and merge-request controls
```

## Local start

Requirements: Python 3.12+, Node 22+, Docker Compose.

```bash
cp .env.example .env
make api-install
make bootstrap
make api-test
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

The default local identity is read from environment variables. HTTP clients cannot select their own access tier. Production refuses `dev` authentication mode.

## Core invariants

1. A source without provenance and an approved immutable version cannot answer a query.
2. Authentication attributes are verified by the server; query bodies cannot expand authorization.
3. Access filtering happens before ranking or generation.
4. Every claim names one or more immutable evidence span identifiers.
5. An answer cannot cite a rejected, quarantined, inactive, or inaccessible version.
6. Retrieved text is data, never an instruction channel.
7. Audit events form a verifiable hash chain.
8. Agent-generated changes merge only through protected GitLab merge requests and independent verification.
9. Unknown evidence state produces abstention, not fluent completion.
10. Formal authorization is an external gate; it is never inferred from passing unit tests.

## Common commands

```bash
make check              # repository validation, tests, lint, typecheck
make bootstrap          # initialize DB and seed a reviewed public fixture
make eval               # frozen evidence and access evaluation
make audit-verify       # verify the persistent hash chain
make infra-up           # generate secrets; start local API + PWA
make infra-support      # also start optional PostgreSQL, Redis, MinIO and OpenTelemetry
make package            # create deterministic source archive
```

## Deployment modes

- `local`: SQLite, local object directory, fixed development identity.
- `controlled`: PostgreSQL/object storage, signed JWT identity, restricted egress.
- `isolated`: private registry, local model gateway, no external provider calls, dedicated runners.

See `docs/architecture/SYSTEM.md`, `docs/architecture/SECURITY.md`, and `docs/protocols/REVIEW_AND_RELEASE.md`.
