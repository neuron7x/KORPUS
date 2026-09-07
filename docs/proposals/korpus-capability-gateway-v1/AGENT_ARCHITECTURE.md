# Multi-Agent Architecture

Agents are bounded execution workers, not authorities.

```text
Owner / Release Authority
        |
  00 Orchestrator
   |-- 01 Repo Forensics
   |-- 02 Architecture
   |-- 03 Contracts
   |-- 04 Policy/Security
   |-- 05 Adapter/MCP
   |-- 06 Side Effects
   |-- 07 Evidence/Audit
   |-- 08 Observability
   |-- 09 Falsification
   |-- 10 Integration Verifier [fresh context]
   |-- 11 Clean-Room Reproducer [fresh worktree]
   `-- 12 Release Handoff
```

Every handoff contains:
`CLAIM -> EXACT SUBJECT -> CHANGE -> INVARIANT -> FALSIFICATION -> EVIDENCE -> BLOCKERS -> N+1`.

The implementation agent cannot be the sole verifier of its own material change in the same
context. This is structurally separated internal verification, not external certification.

After the frozen critical set passes with positive + poisoned controls and exact-state
reproduction, stop. Do not create an infinite verifier-of-verifier chain.
