# Code Agent Execution Order

## Mission

Implement the proposal against live KORPUS without creating a parallel
authorization/evidence/audit system and without infinite post-freeze assurance expansion.

## 0 — Establish truth

Read live `AGENTS.md`, `docs/architecture/SYSTEM.md`, this proposal, exact Git status/HEAD and
compare live code to proposal baseline `578f4ea9caa93ec6211dbe914bf11ae110a6eaed`. Use one isolated implementation
branch/worktree.

## 1 — Discover canonical seams

Find exact current identity, authorization, egress, audit, evidence, transaction,
configuration, bootstrap/DI, telemetry and release-identity code. Fill `ACT_00`.

Do not code against guessed seams.

## 2 — Freeze v1 scope

Base core is mandatory. Select optional profiles (`http-read`, `side-effects`, `mcp`) explicitly.
Freeze applicable `CGW-R001..R020`.

## 3 — Implement core first

Strict types/contracts, exact registry, lifecycle, orchestrator. Prove unknown/deny/malformed
all produce zero adapter calls.

## 4 — Bind canonical KORPUS policy

Use live policy before execution. Never accept authority from request, model, MCP, provider or
adapter. Decision identity is correlation evidence, not a token.

## 5 — Prove the whole flow with a deterministic internal adapter

Do not begin with MCP.

## 6 — Add governed HTTP if selected

Use existing `httpx` and current egress controls. Server-side provider configuration, bounds,
redirect/URL policy, timeout, error normalization, credential redaction.

## 7 — Bind canonical evidence and audit

Wrong/missing/stale evidence fails when required. Required audit failure cannot produce
success.

## 8 — Side effects only after reads close

Durable idempotency, concurrency safety, receipt and `OUTCOME_UNKNOWN` reconciliation.

## 9 — MCP only after base gateway is stable

Remote metadata untrusted; local mapping owns effect/policy; schema drift quarantines;
MCP transport authorization never replaces KORPUS action authorization.

## 10 — Falsify

Run all applicable fixtures plus property/metamorphic/adversarial/concurrency/integration and
critical mutation tests. Implementing agent is not final verifier.

## 11 — Separate verification

Fresh context/worktree attacks authority spoof, substitution, evidence binding, replay, drift,
audit and exact candidate binding. Fill `ACT_06`.

## 12 — Clean-room

Fresh worktree/clone, locked dependencies, no stale generated evidence. Run frozen lane.

## 13 — Freeze and stop

Only P0/frozen-verifier defects expand current work. Everything else -> N+1.

## 14 — Owner handoff

Fill `ACT_07`. Final state `READY_FOR_OWNER_APPROVAL`.
