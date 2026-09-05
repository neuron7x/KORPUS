# KORPUS × OpenClaw Integration v1

**Status:** PROPOSED / THEORY + IMPLEMENTATION FOUNDATION  
**Branch:** `proposal/openclaw-korpus-integration-v1-20260905`  
**Base snapshot:** `main@5528825695f5586112a28c9964f8388c954e6ca9`  
**Scope:** external orchestration/control-plane integration; no production authority granted.

## 1. Purpose

This proposal defines a governed integration between KORPUS and OpenClaw. The objective is to use OpenClaw for channels, agent/session routing, device/node access, scheduled/interactive orchestration and bounded tool execution while preserving KORPUS as the authoritative security, evidence and audit system.

The integration is intentionally asymmetric:

```text
OpenClaw = interaction + orchestration + bounded execution transport
KORPUS   = identity/policy + authorization + evidence + audit + release truth
```

OpenClaw is not promoted to a KORPUS authority plane. KORPUS does not delegate corpus authorization, evidence admission, release authority or audit truth to an external agent runtime.

## 2. Existing KORPUS foundation

KORPUS already contains an MCP boundary in `apps/api/src/korpus/mcp/` and `scripts/run_mcp_server.py`. It exposes evidence-oriented tools such as `korpus_ask`, `korpus_grounds`, `korpus_quote` and `korpus_verify` through the existing HTTP API rather than creating a second data/authority path.

A separate Capability Gateway proposal in PR #44 defines a future generalized boundary for internal/HTTP/MCP adapters. This OpenClaw proposal does **not** merge, modify or depend on PR #44 being accepted. It is designed so that:

1. a read/evidence-only OpenClaw integration can use the current MCP/API boundary;
2. side-effecting capabilities may later bind to the Capability Gateway if and only if that gateway is independently integrated and verified.

## 3. Integration theorem

The core safety statement is:

```text
Related(action, goal) != Authorized(action)
AgentStatement        != Evidence
TransportAuth         != KORPUSAuthorization
Executed(action)      != Verified(action)
```

For an OpenClaw-originated invocation `i`, KORPUS may execute only when:

```text
Admit(i) =
    AuthenticatedKorpusSubject(i)
    AND ExactLocalCapability(i)
    AND CanonicalPolicyAllow(i)
    AND InputContractValid(i)
    AND EgressPolicySatisfied(i)
    AND EffectGuardSatisfied(i)
```

A critical result may be returned only when:

```text
ReturnCritical(r) =
    OutputContractValid(r)
    AND RequiredEvidenceValid(r)
    AND RequiredAuditCommitted(r)
```

Unknown state is not permission.

## 4. Target architecture

```text
Telegram / WhatsApp / WebChat / CLI / iOS / Android / Linux node
                         |
                         v
                  OpenClaw Gateway
             sessions / channels / routing
                         |
                         v
                 OpenClaw Agent Runtime
                         |
            bounded MCP/API capability calls
                         |
                         v
              KORPUS Integration Boundary
              MCP now / Gateway later
                         |
          +--------------+---------------+
          |              |               |
          v              v               v
      Identity        Policy/ABAC     Egress/Effects
          |              |               |
          +--------------+---------------+
                         |
                         v
          Authorized Retrieval / Operations
                         |
                         v
              Evidence Admission + Audit
                         |
                         v
                  Governed Result
```

## 5. Design commitments

1. **KORPUS remains authoritative.** OpenClaw may request actions but cannot grant itself access.
2. **MCP is a protocol boundary, not a trust boundary.** A valid MCP/Gateway token proves transport/session access, not logical authorization.
3. **Remote metadata is untrusted.** Tool names, schemas, annotations and model text do not create KORPUS permissions.
4. **No secret/corpus overexposure.** The adapter releases only the minimum material admitted by KORPUS policy.
5. **Read before write.** Initial integration is evidence/read-oriented. Mutations require explicit effect classes, idempotency and reconciliation semantics.
6. **No silent fallback.** Unknown, stale, malformed, unauthorized or unverifiable conditions fail closed.
7. **One audit truth.** KORPUS audit remains canonical for KORPUS actions; OpenClaw logs are operational context only.
8. **One release truth.** OpenClaw configuration cannot change KORPUS release identity or evidence validity.
9. **Structural separation.** The agent/runtime proposing an action is not accepted as evidence that the action is authorized or correct.
10. **Capability minimization.** OpenClaw receives only declared capabilities required for a workflow.

## 6. Phase model

### Phase A — Evidence client

Allowed:
- `korpus_grounds`
- `korpus_ask`
- `korpus_quote`
- `korpus_verify`

Purpose: allow an OpenClaw agent to ground its response in KORPUS without any KORPUS mutation.

### Phase B — Read-only operational capabilities

Examples:
- release/status queries;
- corpus metadata permitted to the subject;
- audit status permitted to the subject;
- environment/runtime observations through typed, non-mutating capabilities.

### Phase C — Bounded side effects

Only after effect-control implementation is verified:
- explicit capability id/version;
- authorization resource binding;
- input/output contracts;
- idempotency;
- effect ledger;
- known/unknown outcome handling;
- canonical audit.

### Phase D — Multi-channel/device orchestration

OpenClaw may route approved workflows across messaging channels and paired nodes. Device/channel availability does not broaden KORPUS authority.

## 7. Non-goals

This proposal does not:
- make OpenClaw a database or evidence source;
- allow an LLM to self-authorize;
- expose unrestricted shell/filesystem access to KORPUS production;
- treat a channel identity as a KORPUS principal without explicit identity binding;
- bypass PostgreSQL RLS/ABAC;
- replace KORPUS audit with OpenClaw session history;
- merge PR #44;
- grant production authorization.

## 8. Documents

- `ARCHITECTURE_AND_THEORY.md` — formal system model and trust boundaries.
- `SECURITY_AND_THREAT_MODEL.md` — adversary model, attack surfaces and controls.
- `CAPABILITY_AND_EFFECT_MODEL.md` — capability semantics, effect classes, idempotency and reconciliation.
- `IMPLEMENTATION_PLAN.md` — staged implementation and repository changes.
- `VERIFICATION_AND_ACCEPTANCE.md` — falsification tests, acceptance gates and stop conditions.
- `OPENCLAW_FACTS_AND_REFERENCES.md` — current OpenClaw facts used by this proposal and source references.
- `DECISIONS/ADR-0001-openclaw-is-external-orchestration.md` — authority decision.

## 9. Merge posture

This PR should remain **draft** until executable implementation exists and the proposal's acceptance tests are satisfied. Documentation is a design contract, not runtime evidence.

**Current verdict:** `THEORY_READY / IMPLEMENTATION_NOT_YET_AUTHORIZED`.
