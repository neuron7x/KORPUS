# KORPUS Capability Gateway v1 — Theory Branch

Repository: `neuron7x/KORPUS`  
Target: `main`  
Inspected baseline: `578f4ea9caa93ec6211dbe914bf11ae110a6eaed`  
Proposed branch: `proposal/korpus-capability-gateway-v1-20260904`  
Package mode: additive documentation/specification only  
Implementation status: NOT IMPLEMENTED  
Production authority: NONE

## Mission

Define a complete, implementation-ready theory branch for a universal KORPUS capability and
integration gateway. A coding agent can later implement it against live code without
inventing architecture, policy, contracts, tests, work acts, or release semantics.

The target execution chain is:

```text
IDENTITY
  -> KORPUS POLICY
  -> CAPABILITY REGISTRY
  -> INPUT CONTRACT
  -> EFFECT GUARD
  -> ADAPTER EXECUTION
  -> OUTPUT CONTRACT
  -> EVIDENCE VALIDATION
  -> AUDIT
  -> GOVERNED RESULT
```

The adapter can extend what KORPUS can do. It cannot extend what KORPUS is authorized to do.

## Merge-conflict strategy

This ZIP adds only `docs/proposals/korpus-capability-gateway-v1/`. At the inspected baseline,
that path does not exist on `main`. No existing source, test, configuration, release, or
manifest file is overwritten by this package.

This minimizes content-level conflicts with the inspected `main`; it cannot guarantee that a
future `main` will not independently create the same path.

## Primary invariants

1. Policy precedes external execution.
2. Unknown capability means deny.
3. Invalid input means reject before adapter execution.
4. Request/model/adapter/remote metadata never supplies KORPUS authorization.
5. Invalid output cannot become success.
6. Critical result without required valid evidence is rejected or abstained.
7. Side effects require explicit effect authorization and durable idempotency.
8. Ambiguous effect timeout becomes `OUTCOME_UNKNOWN`, never assumed no-effect.
9. Required audit failure prevents success.
10. Telemetry is observability, not audit authority.
11. Remote/MCP discovery data is untrusted until locally mapped and validated.
12. Implementation and final verification use structurally separated contexts.
13. The Owner remains final production release authority.

## Main handoff

Start with `CODE_AGENT_EXECUTION_ORDER.md`, then execute the finite DAG in
`IMPLEMENTATION_GRAPH.yaml`. The future coding worker must re-inspect live `main`; this
proposal is design provenance, not permission to assume source seams remain unchanged.
