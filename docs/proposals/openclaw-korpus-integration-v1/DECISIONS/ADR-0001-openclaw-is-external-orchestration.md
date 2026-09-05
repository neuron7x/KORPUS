# ADR-0001 — OpenClaw Is External Orchestration, Not KORPUS Authority

**Status:** PROPOSED  
**Date:** 2026-09-05

## Context

KORPUS requires a practical orchestration surface across messaging channels, sessions, devices/nodes, automation and agent runtimes. OpenClaw provides a suitable external control-plane substrate for those interaction functions.

KORPUS already owns a stronger and different set of invariants: authenticated subject interpretation, authorization, controlled retrieval, evidence admission, audit, effect safety and release authority.

If OpenClaw were permitted to grant KORPUS authority directly, the system would acquire two independent sources of permission and could no longer prove that one canonical policy boundary controls protected actions.

## Decision

OpenClaw SHALL be integrated as an **external orchestration and transport layer**.

OpenClaw MAY:
- receive and route user/channel interactions;
- manage OpenClaw sessions and agent routing;
- expose paired node/device capabilities;
- trigger scheduled/event-driven workflows;
- invoke explicitly registered KORPUS capabilities;
- carry governed results back to authorized routes.

OpenClaw SHALL NOT:
- determine KORPUS roles/clearance/corpus access;
- grant KORPUS action authority;
- become a factual/evidence source merely by producing model text;
- replace KORPUS canonical audit;
- hold KORPUS release-signing/production authority by default;
- create capabilities dynamically with execution authority from remote metadata alone.

## Formal rule

```text
OpenClawAuth(x) != KORPUSAuthorize(x)
OpenClawRoute(x) != KORPUSSubject(x)
OpenClawOutput(x) != KORPUSEvidence(x)
```

KORPUS re-authorizes every protected invocation.

## Consequences

### Positive

- OpenClaw can expand channels/devices/automation without expanding KORPUS authority roots.
- OpenClaw compromise is constrained by KORPUS-side capability/policy boundaries.
- Current KORPUS MCP evidence tools can be reused.
- Future Capability Gateway integration remains compatible.
- Audit and evidence semantics stay local and testable.

### Cost

- identity binding must be explicit;
- some operations require duplicate-looking checks at both OpenClaw and KORPUS layers;
- side effects require KORPUS effect/idempotency/reconciliation state even if OpenClaw has its own runtime logs;
- broad generic OpenClaw tools cannot automatically become KORPUS production capabilities.

These costs are intentional because they preserve a single authority model.

## Rejected alternatives

### A. Trust OpenClaw Gateway token as KORPUS permission
Rejected: transport/session authentication does not encode KORPUS corpus/resource policy.

### B. Give OpenClaw unrestricted KORPUS service credentials
Rejected: violates least authority and makes agent/tool compromise equivalent to KORPUS authorization compromise.

### C. Let the LLM decide when an action is safe
Rejected: model reasoning is not a deterministic policy authority and is vulnerable to prompt/tool-output injection.

### D. Duplicate authorization policy in OpenClaw config
Rejected: creates policy drift and a second truth source.

### E. Merge OpenClaw directly into the KORPUS kernel
Rejected: increases trusted computing base and couples fast-changing orchestration code to evidence/security invariants.

## Validation

This ADR is considered correctly implemented only when negative tests prove that:
- a valid OpenClaw credential cannot perform an unauthorized KORPUS action;
- injected role/clearance metadata cannot widen access;
- unknown remote tools cannot execute;
- OpenClaw/session text cannot satisfy KORPUS factual evidence admission;
- KORPUS remains operational when OpenClaw is disabled.

## Relationship to PR #44

The Capability Gateway proposal's “MCP as adapter, not authority” principle is semantically aligned with this ADR. This proposal does not merge or alter PR #44; any future convergence requires separate repository integration and verification.
