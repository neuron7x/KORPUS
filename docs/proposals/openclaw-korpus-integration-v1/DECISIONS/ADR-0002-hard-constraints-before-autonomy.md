# ADR-0002 — Hard Constraints Before Autonomy Optimization

**Status:** PROPOSED

## Context

Agentic systems are often described with one broad notion of “autonomy”. That is insufficient for KORPUS because a useful action can still be unauthorized, overexposed, unverifiable or operationally ambiguous.

A scalar utility function that permits enough task value to compensate for an authority violation is invalid for this system.

## Decision

KORPUS uses constrained lexicographic decision semantics.

First compute admissibility:

```text
Admissible(a) =
  AuthenticatedSubject
  ∧ ExactCapability
  ∧ ExactResource
  ∧ CanonicalPolicyAllow
  ∧ InputValid
  ∧ EgressValid
  ∧ EffectGuardSatisfied
  ∧ RequiredVerificationAvailable
```

Only admissible actions may be ranked for convenience, cost, latency or goal progress.

Autonomy is capability/context-specific, not global.

```text
read/evidence automation
!=
bounded write automation
!=
privileged authority-changing automation
```

## Consequences

- LLM proposal quality cannot widen authority.
- safety invariants are not tunable weights;
- no admissible action means abstain/refuse/escalate;
- autonomy can increase gradually by verified capability class;
- high-impact operations can remain owner-controlled indefinitely.

## Falsification

This ADR is violated if any implementation path allows:
- model confidence/utility to override policy denial;
- route/node/tool availability to grant KORPUS permission;
- optimization logic to execute when hard state is unknown.
