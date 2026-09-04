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

The structured `CapabilityGatewayPorts` composition path repeats the same exact safety check
at construction time, making an unsafe effectful structured composition non-executable even
if a caller accidentally skips preflight. The legacy keyword-port constructor is retained
only as a transitional unit-test/backward-compatibility shim and is **not deployment
admission**; owner-approved effectful composition must use structured ports plus preflight.

## Consequences
- Frozen v1 wire/schema compatibility is preserved.
- Effectful deployment cannot rely on implicit rollback assumptions.
- Same-version local contract mutation invalidates the safety declaration.
- Deployment admission and structured runtime composition independently enforce the safety
  prerequisite without turning it into authorization.
- The legacy constructor remains an explicit migration debt and should be removed after all
  callers move to structured ports.
- A future capability-contract version may inline equivalent semantics only through an
  explicit versioned contract migration; this ADR does not mutate v1 retrospectively.
