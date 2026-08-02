# Korpus Platform

Evidence-first knowledge and training platform for Ukrainian service members. The
repository is a production-oriented starting point: it contains an executable API,
a minimal PWA shell, data contracts, local infrastructure, agent policies, eval
fixtures, architecture decisions, governance protocols, and delivery runbooks.

The product is **not** an autonomous operational decision-maker. It retrieves
approved sources, exposes citations and uncertainty, produces administrative
drafts, and supports reviewed training curricula. It must abstain when evidence or
authorization is insufficient.

## Product promise

> Find the right approved source, explain what it says, show exactly where it says
> it, and say "insufficient evidence" when the corpus cannot support an answer.

## Repository map

```text
apps/api/          FastAPI modular-monolith backend
apps/web/          Next.js PWA shell
packages/contracts/ Versioned JSON Schemas shared across boundaries
agents/prompts/    Versioned agent policies, never hidden business logic
docs/              Product, architecture, governance, protocols, ADRs, research
evals/             Golden datasets and quality gates
infra/             Local infrastructure configuration
scripts/           Deterministic validation and operational scripts
```

## Quick start

Requirements: Docker Compose, Python 3.12+, Node 22+, pnpm 10+.

```bash
cp .env.example .env
docker compose up -d postgres redis minio
make api-install
make api-test
make api-run
```

In another terminal:

```bash
make web-install
make web-run
```

API: `http://localhost:8000`; web: `http://localhost:3000`; API docs:
`http://localhost:8000/docs`.

The default local provider is `stub`, so tests and the health endpoint require no
API key. External LLM calls are opt-in and must pass the data-policy gate.

## Non-negotiable invariants

1. No source enters the answerable corpus without provenance and review state.
2. Every substantive claim maps to one or more immutable evidence spans.
3. Retrieval confidence and answer faithfulness are measured separately.
4. Restricted corpora are physically and logically separated from public corpora.
5. User-generated text and retrieved documents are untrusted input, never system
   instructions.
6. Generation cannot expand a user's authorization.
7. High-risk or clinical content requires a dedicated policy and human review.
8. Model/provider changes pass the same frozen eval set before promotion.

See [docs/product/SPECIFICATION.md](docs/product/SPECIFICATION.md) and
[docs/architecture/SYSTEM.md](docs/architecture/SYSTEM.md).

