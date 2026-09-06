# OpenClaw × KORPUS Architecture Decision Index

## ADR-0001 — OpenClaw Is External Orchestration, Not Authority

OpenClaw provides channels, sessions, routing, nodes and bounded orchestration. KORPUS retains identity, authorization, evidence admission, effect safety, canonical audit and release authority.

## ADR-0002 — Hard Constraints Before Autonomy Optimization

Safety/authority/evidence/effect constraints define the admissible action set. Utility, convenience, latency and autonomy are optimized only inside that set.

## ADR-0003 — Closed-Loop Exact-State Verification

Critical workflows observe actual post-state, verify exact bindings and treat ambiguous effects as `OUTCOME_UNKNOWN` until reconciliation. Actor-reported success is not sufficient authority.

## Decision law

A future ADR may refine these decisions but MUST NOT silently contradict them. If implementation requires a contradiction, create an explicit superseding ADR with migration, risk and verification consequences.
