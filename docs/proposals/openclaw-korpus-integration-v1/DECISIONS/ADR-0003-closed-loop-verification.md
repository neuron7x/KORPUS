# ADR-0003 — Closed-Loop Exact-State Verification

**Status:** PROPOSED

## Context

A distributed agentic workflow can return a plausible success response even when:
- the wrong resource was changed;
- a remote effect committed but the response was lost;
- evidence belongs to another release;
- a route changed before delivery;
- an adapter/provider self-reported success incorrectly.

Therefore `execution response == truth` is not an acceptable system model.

## Decision

Critical workflows use a closed loop:

```text
observe
 -> propose
 -> bind
 -> authorize
 -> execute
 -> observe actual post-state
 -> verify
 -> audit
 -> deliver
```

Critical implementation claims require exact-state evidence:

```text
positive fixture -> PASS
falsifying fixture -> FAIL
subject binding -> exact candidate
```

For ambiguous external effects:

```text
cannot prove commit
AND cannot prove no effect
-> OUTCOME_UNKNOWN
-> reconcile before retry/success
```

## Consequences

- adapter `success=true` is not sufficient for critical effect verification;
- reports/evidence must bind exact source/release/config state;
- timeouts require effect-specific semantics;
- delivery success is separate from execution success;
- critical gates need liveness/negative controls;
- a false-PASS-capable verifier is itself a release defect.

## Falsification

This ADR is violated if:
- timeout is blindly mapped to success/failure after possible effect;
- an old report is admitted solely because path/name matches;
- a critical action returns success before required audit/verification;
- verification trusts only the actor’s own claim.
