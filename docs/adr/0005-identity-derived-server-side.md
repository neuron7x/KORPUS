# ADR-0005: Identity is derived server-side; the wire carries no tier

Status: accepted · Date: 2026-08-02

## Context

The first cut of `Query` carried `user_tier: AccessTier = AccessTier.PUBLIC`. A field
on the request body is set by whoever sends the request. A caller could therefore
declare itself `restricted` and the pipeline would have honoured it, because nothing
downstream distinguished a claim about identity from identity itself.

ADR-0004 already required authorized corpora to be derived server-side. That decision
was documented and not implemented: `ACCESS_DENIED` existed in the enum and was
unreachable in code, and no comparison of tiers existed anywhere in the pipeline.

## Decision

1. `Query` declares `extra="forbid"` and carries no tier. A request that names a tier
   is rejected with 422 rather than silently ignored — silent ignoring teaches a
   client that the field works.
2. A `PrincipalResolver` port derives the caller. `AnswerQuery.execute` takes a
   `Principal` and never reads identity from the query.
3. `StaticPrincipalResolver` is marked `development_only`. `enforce_startup_invariants`
   refuses to boot in `production` with it. The absence of real authentication is a
   startup failure, not a quiet authorization hole.
4. Authorization runs before retrieval; the allowed tier set is passed *into* the
   retriever so an adapter with per-tier indexes can honour it at the index boundary.
5. The same check is repeated on whatever the retriever returned. A defective or
   replaced adapter must not be able to widen disclosure on its own; a violation
   records `evidence.tier_violation` and forces `requires_human_review`.

## Consequences

- Anonymous callers see the public tier only. Raising a tier requires a token the
  server already knows.
- Requesting a corpus the principal does not hold is a direct `access_denied` without
  touching the index. Corpora that were *not* requested are filtered silently, so the
  answer path never confirms the existence of material above the reader's tier.
- Real authentication (OIDC per SECURITY.md) is still absent. What exists is a refusal
  to pretend otherwise: production will not start.

## Falsification

`tests/test_domain_access.py`, `tests/test_api_http.py::test_client_cannot_declare_its_own_tier`,
`test_a_non_bearer_scheme_is_not_accepted_as_a_token`, and mutants `access-01..06`,
`models-09`, `routes-01`, `memory-04`, `startup-01` in `tools/mutants.json`. Deleting
any part of this decision from the code turns at least one of them red.
