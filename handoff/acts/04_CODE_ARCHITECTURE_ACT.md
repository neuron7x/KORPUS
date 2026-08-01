# Act 04 — code and architecture

## Architectural style

- Modular monolith with explicit application, domain, security and infrastructure layers.
- Ports/adapters boundaries for retrieval, storage, identity, embeddings, audit anchoring and observability.
- Relational source of truth; indexes and generated artifacts are rebuildable derivatives.
- Fail-closed controlled mode.

## Core invariants

1. Inaccessible text cannot enter ranking, answers, citations, telemetry or cache identity.
2. Only approved and temporally valid versions may answer.
3. Every claim equals a cited source substring and verifies through offsets and hashes.
4. Retrieved text is data, never an instruction channel.
5. Insufficient or contradictory evidence produces abstention.
6. Metadata, spans and audit events preserve transaction semantics.
7. Audit chain, head, outbox and external checkpoint must reconcile.
8. Candidate work is bounded before application reranking.
9. Same source/config/query produces deterministic semantic output.
10. Agents cannot approve their own work or bypass protected merge gates.

## Known code debt

The remaining code debt is authoritative in `docs/operations/TECHNICAL_DEBT_V5.md` and `docs/audit/closure/KORPUS_v5_REMAINING_DEBT.json`. Principal items: `SqlRepository` decomposition, configuration complexity, broad exception narrowing, structured-document evaluation, embedding lifecycle, retention scheduler, SIEM and UI administration.
