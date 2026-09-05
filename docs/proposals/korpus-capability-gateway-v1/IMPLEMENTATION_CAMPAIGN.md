# Capability Gateway implementation campaign

Status: ACTIVE_IMPLEMENTATION

Base: `main@578f4ea9caa93ec6211dbe914bf11ae110a6eaed`

Branch: `proposal/korpus-capability-gateway-v1-20260904`

Merge policy: **DO NOT MERGE** until the owner explicitly authorizes merge and all required gates are satisfied.

## Execution law

1. Re-read live integration seams before each work package.
2. Preserve KORPUS identity, policy, RLS, evidence, audit and egress authority boundaries.
3. Implement the capability gateway as an additive application-layer PEP; do not create a parallel authorization stack.
4. Exact capability id + exact version resolution only.
5. Unknown/malformed/unauthorized/ambiguous states fail closed.
6. Side effects require durable idempotency semantics before execution.
7. Transport timeout is not evidence of non-execution.
8. External/MCP metadata is untrusted adapter metadata, never policy authority.
9. Tests must target falsifiable invariants and negative controls, not coverage alone.
10. Every implementation claim must be bound to a concrete commit/check artifact.

## Campaign sequence

- WP0 live seam revalidation
- WP1 domain/contracts
- WP2 exact registry/resolution
- WP3 canonical policy bridge
- WP4 execution state machine/orchestrator
- WP5 side-effect idempotency/reconciliation
- WP6 adapters/MCP boundary
- WP7 evidence + canonical audit integration
- WP8 telemetry/health
- WP9 composition/configuration
- WP10 API/operator surface where justified
- WP11 adversarial/concurrency/property tests
- WP12 CI/quality repair loop
- WP13 handoff evidence

This file records the active campaign only. It does not mark any work package implemented or accepted.
