# KORPUS × OpenClaw Integration v1

**Status:** PROPOSED / THEORY + IMPLEMENTATION FOUNDATION  
**Branch:** `proposal/openclaw-korpus-integration-v1-20260905`  
**Base snapshot:** `main@5528825695f5586112a28c9964f8388c954e6ca9`  
**Scope:** external orchestration/control-plane integration; no production authority granted.

---

## 0. Executive thesis

This proposal defines a governed integration between KORPUS and OpenClaw. The objective is to use OpenClaw for channels, agent/session routing, device/node access, scheduled/interactive orchestration and bounded tool execution while preserving KORPUS as the authoritative security, evidence, effect-safety, audit and release system.

The integration is intentionally asymmetric:

```text
OpenClaw = interaction + orchestration + bounded execution transport
KORPUS   = identity/policy + authorization + evidence + effect safety + audit + release truth
```

OpenClaw is not promoted to a KORPUS authority plane. KORPUS does not delegate corpus authorization, evidence admission, release authority or canonical audit truth to an external agent runtime.

The design standard is first-principles and falsification-first:

```text
primitive state
 -> explicit authority
 -> typed capability
 -> exact resource
 -> bounded information flow
 -> bounded effect
 -> observable post-state
 -> verifier
 -> canonical audit
 -> exact-state evidence
```

---

## 1. Existing KORPUS foundation

KORPUS already contains an MCP boundary in `apps/api/src/korpus/mcp/` and `scripts/run_mcp_server.py`. It exposes evidence-oriented tools such as `korpus_ask`, `korpus_grounds`, `korpus_quote` and `korpus_verify` through the existing HTTP API rather than creating a second data/authority path.

A separate Capability Gateway proposal in PR #44 defines a future generalized boundary for internal/HTTP/MCP adapters. This OpenClaw proposal does **not** merge, modify or depend on PR #44 being accepted. It is designed so that:

1. a read/evidence-only OpenClaw integration can use the current MCP/API boundary;
2. side-effecting capabilities may later bind to the Capability Gateway if and only if that gateway is independently integrated and verified.

---

## 2. Integration theorem

The core safety statement is:

```text
Related(action, goal) != Authorized(action)
AgentStatement        != Evidence
TransportAuth         != KORPUSAuthorization
Executed(action)      != Verified(action)
NodePaired            != KORPUSDataAuthorized
ToolAvailable         != CapabilityAuthorized
```

For an OpenClaw-originated invocation `i`, KORPUS may execute only when:

```text
Admit(i) =
    AuthenticatedKorpusSubject(i)
    AND ExactLocalCapability(i)
    AND ExactResourceBound(i)
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

---

## 3. Hard constraints before optimization

The proposal does not use a single scalar utility that can trade safety against convenience.

First define the admissible action set:

```text
A_admissible(X) = {
  a | Authority(a,X)
      ∧ ResourceBound(a,X)
      ∧ InputValid(a)
      ∧ EgressValid(a,X)
      ∧ EffectGuardSatisfied(a,X)
      ∧ RequiredVerificationAvailable(a)
}
```

Only after hard constraints pass may the orchestrator optimize latency, cost, convenience or goal progress.

```text
Safety invariants are constraints, not weights.
```

See `FIRST_PRINCIPLES_AND_OBJECTIVE_FUNCTION.md`.

---

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

---

## 5. Closed-loop operating model

The architecture is deliberately closed-loop:

```text
OBSERVE
 -> PARSE INTENT
 -> PROPOSE
 -> RESOLVE EXACT CAPABILITY
 -> BIND RESOURCE
 -> AUTHORIZE
 -> VALIDATE INPUT / EGRESS / EFFECT
 -> EXECUTE
 -> OBSERVE ACTUAL RESULT
 -> VERIFY
 -> AUDIT
 -> DELIVER TO AUTHORIZED ROUTE
 -> UPDATE PLAN / SESSION
```

`Open-loop = propose -> execute -> assume` is explicitly rejected for critical operations.

See `CONTROL_THEORY_AND_AUTONOMY.md`.

---

## 6. Design commitments

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
11. **Outcome ambiguity is explicit.** Transport uncertainty after possible side effect becomes `OUTCOME_UNKNOWN`, never guessed success/failure.
12. **Delivery is separately authorized.** A valid internal result is not automatically safe for every channel/node.
13. **Autonomy is capability-specific.** Read automation may be allowed while writes/privileged operations remain gated.
14. **Every critical positive claim needs a poison.** A gate that cannot be made red is not release authority.

---

## 7. Phase model

### Phase A — Evidence client

Allowed:
- `korpus_grounds`
- `korpus_ask`
- `korpus_quote`
- `korpus_verify`

Purpose: allow an OpenClaw agent to ground its response in KORPUS without any KORPUS mutation.

Recommended flow:

```text
message
 -> bind route/subject
 -> korpus_grounds
 -> korpus_ask
 -> compose
 -> korpus_verify
 -> delivery authorization
 -> response
```

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
- durable effect ledger;
- known/unknown outcome handling;
- reconciliation;
- canonical audit.

### Phase D — Multi-channel/device orchestration

OpenClaw may route approved workflows across messaging channels and paired nodes. Device/channel availability does not broaden KORPUS authority.

---

## 8. Autonomy model

The proposal uses bounded levels rather than one global “autonomous” switch:

```text
L0 observe
L1 recommend/draft
L2 automatic read
L3 reversible bounded write
L4 transactional effect + reconciliation
L5 privileged authority-changing action
```

Initial posture:

```text
read/evidence <= L2 after verification
side effects  = disabled until effect controls pass
privileged    = owner-controlled / denied to agent by default
```

---

## 9. Information-flow law

Authorization and disclosure are separate decisions.

```text
ActionAuthorized != ResultAuthorizedForDestination
```

Protected information may flow only to a destination permitted for its class/purpose, and only in the minimum amount required for the admitted action.

See `INFORMATION_FLOW_AND_PRIVACY_MODEL.md`.

---

## 10. Distributed-failure law

```text
RequestSent != RequestReceived
RequestReceived != EffectCommitted
EffectCommitted != ResponseReceived
ResponseReceived != VerifiedSuccess
```

Therefore the system has explicit idempotency, effect states, `OUTCOME_UNKNOWN`, reconciliation and bounded retry semantics before side-effect autonomy is allowed.

See `DISTRIBUTED_SYSTEMS_AND_FAILURE_SEMANTICS.md`.

---

## 11. Verification philosophy

For each critical claim:

```text
positive fixture -> PASS
falsifying poison -> FAIL
critical guard mutation -> killed
```

Evidence must bind exact implementation state.

A green test belonging to another source SHA is historical evidence only.

See:
- `EVALUATION_LEARNING_AND_FEEDBACK.md`
- `TRACEABILITY_AND_ACCEPTANCE_MATRIX.md`
- `VERIFICATION_AND_ACCEPTANCE.md`

---

## 12. Academic and first-principles calibration

The proposal deliberately distinguishes engineering authority from pedagogical inspiration.

It uses:
- official OpenClaw docs for current OpenClaw facts;
- official MCP specification for protocol/security facts;
- NIST SP 800-207 for zero-trust principles;
- NIST AI RMF for risk/governance framing;
- RFC 9110 for HTTP safe/idempotent semantics;
- Andrej Karpathy’s *Zero to Hero* and *Software Is Changing (Again)* as pedagogical/contextual references for building mechanisms from primitives, partial autonomy, human–AI loops and agent-oriented infrastructure.

None of those sources substitute for executable KORPUS verification.

See `ACADEMIC_FOUNDATIONS_AND_REFERENCE_MAP.md`.

---

## 13. Current external verification snapshot

Version-sensitive OpenClaw/MCP facts checked while writing the proposal are frozen in:

- `OPENCLAW_CURRENT_VERIFICATION_2026-09-05.md`

Implementation must reverify them because OpenClaw is actively evolving.

---

## 14. Practical implementation contracts

Concrete proposed shapes for:
- integration identity;
- route envelope;
- route→KORPUS subject binding;
- Phase A tool allowlist;
- grounds/ask/verify workflow;
- error taxonomy;
- token handling;
- future capability/effect/result envelopes;
- exact acceptance gates.

See `IMPLEMENTATION_CONTRACTS_AND_INTERFACES.md`.

---

## 15. Operational rollout

Rollout proceeds by risk surface:

```text
0 offline contracts/evals
1 local read-only evidence
2 one channel
3 multi-channel read-only
4 operational reads
5 one bounded write class
6 transactional effects
7 selected node/device workflows
```

Each promotion requires exact-state acceptance, negative controls and tested disable/rollback.

See `OPERATIONAL_ROLLOUT_AND_RUNBOOK.md`.

---

## 16. Document map

### Core theory

- `FIRST_PRINCIPLES_AND_OBJECTIVE_FUNCTION.md` — primitives, hard constraints, objective/value hierarchy, autonomy theorem.
- `CONTROL_THEORY_AND_AUTONOMY.md` — closed-loop control, partial observability, autonomy levels, feedback and stability.
- `STATE_MACHINE_AND_INVARIANTS.md` — legal transitions, binding tuple, killable invariants and state-machine poisons.
- `DISTRIBUTED_SYSTEMS_AND_FAILURE_SEMANTICS.md` — partial failure, retries, idempotency, outcome ambiguity, reconciliation.
- `INFORMATION_FLOW_AND_PRIVACY_MODEL.md` — data classes, destination policy, cross-tool flow and minimization.

### Architecture and capability system

- `ARCHITECTURE_AND_THEORY.md` — formal system model and trust boundaries.
- `CAPABILITY_AND_EFFECT_MODEL.md` — capability semantics, effect classes, idempotency and reconciliation.
- `IMPLEMENTATION_CONTRACTS_AND_INTERFACES.md` — concrete Phase A/B/C interface contracts.
- `FORMAL_REQUIREMENTS.md` — normative AUTH/CAP/ID/EVD/EGR/EFF/ROUTE/NODE/AUD/OPS/VER/REL requirements.

### Security and verification

- `SECURITY_AND_THREAT_MODEL.md` — adversary model, attack surfaces and controls.
- `EVALUATION_LEARNING_AND_FEEDBACK.md` — eval-driven engineering, failure taxonomy, mutation and learning loop.
- `VERIFICATION_AND_ACCEPTANCE.md` — falsification tests, acceptance gates and stop conditions.
- `TRACEABILITY_AND_ACCEPTANCE_MATRIX.md` — requirement→mechanism→observable→poison→release consequence map.

### Research and factual grounding

- `OPENCLAW_FACTS_AND_REFERENCES.md` — OpenClaw facts used by the initial proposal.
- `OPENCLAW_CURRENT_VERIFICATION_2026-09-05.md` — separately checked current version/protocol snapshot.
- `ACADEMIC_FOUNDATIONS_AND_REFERENCE_MAP.md` — standards, protocol sources, first-principles reference hierarchy.

### Execution

- `IMPLEMENTATION_PLAN.md` — staged repository implementation plan.
- `INTEGRATION_WORKPACKAGES.md` — tactical dependency/work breakdown.
- `OPERATIONAL_ROLLOUT_AND_RUNBOOK.md` — pilot, promotion, kill-switch, incident and rollback model.

### Architecture decisions

- `DECISIONS/ADR-0001-openclaw-is-external-orchestration.md` — OpenClaw is orchestration, not KORPUS authority.

---

## 17. Non-goals

This proposal does not:
- make OpenClaw a database or evidence source;
- allow an LLM to self-authorize;
- expose unrestricted shell/filesystem access to KORPUS production;
- treat a channel identity as a KORPUS principal without explicit identity binding;
- bypass PostgreSQL RLS/ABAC;
- replace KORPUS audit with OpenClaw session history;
- call OpenClaw multi-agent separation “independent external assurance”;
- merge PR #44;
- grant production authorization;
- claim documentation proves the integration is implemented.

---

## 18. Merge posture

This PR should remain **draft** until executable implementation exists and the proposal's acceptance tests are satisfied.

Documentation is a design contract, not runtime evidence.

Current proposal verdict:

```text
THEORY_FOUNDATION = STRONG
EXTERNAL_FACT_SNAPSHOT = RECORDED
IMPLEMENTATION = NOT YET AUTHORIZED BY THIS DOCUMENTATION
PRODUCTION_AUTHORITY = NOT GRANTED
```

The terminal implementation standard is:

```text
exact candidate
+ exact authority
+ bounded data flow
+ bounded effects
+ adversarial falsifiability
+ closed-loop verification
+ canonical audit
+ exact-state evidence
```
