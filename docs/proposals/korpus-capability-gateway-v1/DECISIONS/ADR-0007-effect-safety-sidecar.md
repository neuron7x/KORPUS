# ADR-0007 — Exact-bound side-effect safety declaration

## Status
Accepted for implementation; does not alter the frozen `korpus.capability-spec.v1` contract.

## Context
`SIDE_EFFECT_AND_IDEMPOTENCY_MODEL.md` requires every effectful capability to make
compensation/rollback semantics and irreversibility explicit before execution. The frozen
`CapabilitySpec v1` JSON schema has no field capable of representing that declaration.
Silently extending the frozen schema would destroy contract-freeze semantics; ignoring the
requirement would admit effectful execution with unknown rollback and reconciliation posture.

## Decision
Use a separate **server-owned, exact-bound safety declaration** for effectful capabilities.
The declaration binds:
- exact capability id/version;
- digest of the complete immutable local `CapabilitySpec`;
- compensation mode (`PROVIDER_NATIVE`, `COMPENSATING_ACTION`, or `NONE`);
- explicit irreversibility;
- reconciliation mode;
- exact compensation capability identity when a compensating action is declared;
- operator rationale.

A safety declaration is a safety prerequisite, **not authorization**. It cannot add roles,
permissions, effect classes, egress rights, retry rights, or provider authority. Canonical
policy and explicit effect authorization remain independently required.

Deployment preflight fails closed for every enabled effectful capability that has no exact
safety declaration or whose same-version local contract digest drifted. `NONE` compensation
is admissible only when irreversibility is explicitly true.

Every `CapabilityGateway` construction path repeats the same exact safety check. Structured
ports remain the preferred composition API, but the transitional legacy keyword-port path is
not allowed to weaken effect safety: an enabled effectful capability without an exact-bound
safety declaration is non-executable regardless of constructor form.

The same declaration constrains reconciliation. Automatic reconciliation must resolve the
exact declaration for the current capability contract and use the declared strategy only.
`PROVIDER_STATUS_QUERY` and `PROVIDER_IDEMPOTENCY_LOOKUP` are distinct executable strategies;
a resolver must identify the matching server-owned mode before any provider observation.
`MANUAL` is never implemented by passing a provider resolver through the automatic path and
requires a separate canonical-authorized, canonical-audited operator workflow.

Provider metadata does not choose compensation, irreversibility, or reconciliation mode.
Those remain deployment-owned facts and therefore cannot widen policy authority.

## Consequences
- Frozen v1 wire/schema compatibility is preserved.
- Effectful deployment cannot rely on implicit rollback assumptions.
- Same-version local contract mutation invalidates the safety declaration.
- Deployment admission and every runtime composition path independently enforce the safety
  prerequisite without turning it into authorization.
- Automatic reconciliation cannot silently substitute one recovery strategy for another or
  turn `MANUAL` into provider-driven execution.
- The legacy constructor remains migration debt only; while it exists, it obeys the same
  effect-safety law as structured composition.
- A future capability-contract version may inline equivalent semantics only through an
  explicit versioned contract migration; this ADR does not mutate v1 retrospectively.
