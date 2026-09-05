# Academic Foundations and Reference Map

**Status:** RESEARCH / NORMATIVE SOURCE HIERARCHY FOR PROPOSAL v1  
**Research checkpoint:** 2026-09-05

This document separates three categories that are often mixed incorrectly:

1. **Normative protocol/product facts** — what OpenClaw, MCP, HTTP or KORPUS actually specify.
2. **Engineering principles** — broadly applicable security, control and distributed-systems reasoning.
3. **Pedagogical inspiration** — explanatory methods useful for deriving complex systems from primitives.

No external author or document grants KORPUS production authority. References justify reasoning, terminology and design constraints; executable evidence justifies implementation claims.

---

## 1. Source hierarchy

When sources conflict, prefer:

```text
Level 1  KORPUS machine-owned current release/config/contracts
Level 2  official protocol/product specifications for exact external version
Level 3  official standards/publications
Level 4  peer-reviewed/foundational engineering literature
Level 5  official technical talks/courses by named practitioners
Level 6  community summaries/blogs
Level 7  model inference
```

For KORPUS authority semantics, Level 1 remains authoritative.

External sources cannot widen KORPUS permission.

---

## 2. OpenClaw — official facts

### 2.1 Gateway protocol

Official OpenClaw documentation describes the Gateway WebSocket protocol as the single control plane and node transport for operator and node clients, with role/scope declared at handshake.

Reference:
- https://docs.openclaw.ai/gateway/protocol

Current research snapshot reported stable gateway client/protocol package release `2026.8.1`. This is versioned external state, not a timeless constant.

Design consequence:

```text
OpenClaw Gateway = routing/control transport
OpenClaw Gateway != KORPUS authority plane
```

### 2.2 Gateway clients

Reference:
- https://docs.openclaw.ai/gateway/clients

The official client guide documents separate protocol/client packages, wire-version rules, connection lifecycle and reconnect behavior.

Design consequence:
- pin versions;
- record protocol version;
- test version skew;
- do not infer compatibility from package name alone.

### 2.3 Multi-agent routing

Reference:
- https://docs.openclaw.ai/multi-agent

OpenClaw documents isolated agents with separate workspace/state/session history and channel bindings.

Design consequence:

```text
OpenClawAgentIsolation != independent assurance
```

but it can provide useful orchestration and execution-context separation.

### 2.4 Nodes

Reference:
- https://github.com/openclaw/openclaw/blob/main/docs/nodes/index.md

Official node documentation describes paired node identities and command surfaces including device/system/media commands and node-hosted MCP servers.

Design consequence:

```text
NodePaired != KORPUSDataAuthorized
```

and tool-surface changes must be policy-mapped.

### 2.5 Tool policies

Reference:
- https://docs.openclaw.ai/gateway/config-tools

OpenClaw provides orchestration-side tool allow/deny profiles and sandbox controls, including MCP/plugin tools.

Design consequence:

```text
OpenClaw tool policy = defense-in-depth narrowing
KORPUS policy        = authoritative KORPUS permission
```

---

## 3. Model Context Protocol — official specification

Reference checkpoint:
- https://modelcontextprotocol.io/specification/2025-06-18

The MCP specification defines a host/client/server architecture over JSON-RPC, capability negotiation, tools/resources/prompts, progress/cancellation/error/logging facilities, and explicit security/trust considerations.

The specification explicitly warns that tools can represent arbitrary code execution, that tool descriptions/annotations should be treated with caution, and that applications need authorization and consent controls.

Design consequences:

```text
MCP transport/capability negotiation != application authorization
ToolDescription != TrustedInstruction
MCPToolAvailable != KORPUSCapabilityAuthorized
```

KORPUS therefore performs local capability mapping and policy evaluation even when MCP connection/authentication succeeds.

---

## 4. Zero Trust — NIST SP 800-207

References:
- https://csrc.nist.gov/pubs/sp/800/207/final
- https://doi.org/10.6028/NIST.SP.800-207

NIST SP 800-207 removes implicit trust based on network location/ownership and emphasizes authentication/authorization around subjects, devices and resources.

Relevant design principles:
- no trust because traffic is “local”;
- no trust because a device is paired;
- no trust because OpenClaw and KORPUS run on the same host;
- protect resources, not merely network segments;
- subject/device authentication and resource authorization remain discrete decisions.

KORPUS mapping:

```text
GatewayConnected != Authorized
NodePaired != Authorized
MCPTokenValid != Authorized
SameHost != Trusted
```

---

## 5. NIST AI Risk Management Framework

Reference:
- https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10

AI RMF 1.0 provides a use-case-agnostic framework for managing AI-system risks and emphasizes operationalization, measurement and trustworthy use rather than assuming model capability implies system trustworthiness.

Design consequence:
- separate model capability from system control;
- name risk contexts;
- measure behavior;
- preserve governance and accountability across lifecycle.

This proposal does not claim AI RMF compliance merely because it cites the framework.

---

## 6. HTTP semantics — RFC 9110

Reference:
- https://www.rfc-editor.org/rfc/rfc9110.html

RFC 9110 defines safe and idempotent method semantics and explains why idempotent operations can often be retried after communication failures.

Design consequence:
- retry semantics must be explicit;
- application logical effect matters more than superficial verb name;
- non-idempotent/ambiguous operations require reconciliation rather than blind retry.

KORPUS therefore models effect idempotency at capability level.

---

## 7. First-principles pedagogy — Andrej Karpathy

### 7.1 Neural Networks: Zero to Hero

References:
- https://karpathy.ai/zero-to-hero.html
- https://github.com/karpathy/nn-zero-to-hero

The course is explicitly built from basics toward modern neural networks by implementing mechanisms in code step-by-step.

This proposal uses the same **pedagogical standard**, not neural-network mathematics as system authority:

```text
start from primitives
make hidden transformations explicit
build small mechanisms first
derive abstractions from mechanism
exercise them in code
```

Applied here:
- define Subject, Route, Capability, Resource, Evidence, Effect;
- define state transitions;
- define objective under hard constraints;
- derive OpenClaw integration behavior from those primitives.

### 7.2 Software Is Changing (Again)

Reference:
- https://www.youtube.com/watch?v=LCEmiRjPEtQ

The 2025 talk discusses LLMs as a new programmable computing layer, partial autonomy, human–AI collaboration loops and the need to build infrastructure for agents.

This proposal translates those themes into bounded engineering mechanisms:

```text
partial autonomy -> capability-specific autonomy levels
build for agents -> typed machine-readable tools/contracts
human-AI loop -> explicit approval/verification where objective oracle absent
LLM fallibility -> model proposal separated from deterministic authority
```

The talk is contextual/pedagogical, not a security standard.

---

## 8. Foundational security principles

The proposal deliberately aligns with long-standing security ideas such as:
- least privilege;
- complete mediation;
- fail-safe defaults;
- separation of privilege/authority;
- economy of mechanism;
- explicit resource identity.

These principles are expressed concretely here through:
- local capability registry;
- KORPUS authorization on every protected action;
- deny on unknown;
- structural separation of proposal/execution/verification;
- minimal data egress;
- bounded adapters.

A future bibliography revision may add canonical historical references where licensing/source access is verified; current design does not depend on a citation to make those invariants executable.

---

## 9. Control theory

This proposal uses control-theoretic concepts as an engineering abstraction:
- state;
- observation;
- controller;
- actuator;
- feedback;
- stability;
- gain/amplification;
- closed-loop verification.

No claim is made that software-agent workflows are linear dynamical systems.

The useful transfer is structural:

```text
open-loop agent:
  propose -> execute -> assume success

closed-loop integration:
  observe -> propose -> authorize -> execute -> observe -> verify -> update
```

The second is operationally superior because failure and environment drift become observable.

---

## 10. Distributed systems

Core adopted principles:
- partial failure is normal;
- network timeout does not reveal external effect state;
- exactly-once execution is not assumed;
- retries require idempotency/reconciliation semantics;
- timestamps are not identity;
- causal IDs matter;
- crash recovery must preserve effect ambiguity.

These are encoded in:
- effect ledger;
- `OUTCOME_UNKNOWN`;
- reconciliation;
- idempotency binding;
- version/digest subject binding.

---

## 11. Evidence hierarchy inside the proposal

When writing a design claim, classify it:

```text
FACT_EXTERNAL_CURRENT
  current fact from official OpenClaw/MCP documentation

FACT_KORPUS_CURRENT
  current fact from KORPUS source/config

NORMATIVE_DECISION
  design rule chosen by this proposal

DERIVED_REQUIREMENT
  requirement logically following from decisions/invariants

HYPOTHESIS
  expected property not yet implemented/verified

VERIFIED_IMPLEMENTATION
  executable evidence exists for exact candidate
```

Documentation must not label a hypothesis as verified implementation.

---

## 12. Current verified external facts used by v1 theory

As of the research checkpoint:

```text
OpenClaw:
  Gateway is central session/routing/node control plane.
  Gateway clients use a versioned WebSocket protocol.
  Multi-agent routing supports isolated agent workspaces/state/session stores.
  Nodes expose command surfaces and can host MCP servers.
  Tool policies can narrow plugin/MCP tool visibility.

MCP:
  standardized host/client/server protocol.
  tools/resources/prompts are explicit protocol features.
  security guidance treats tool execution and tool descriptions as trust-sensitive.

KORPUS:
  current main already has an MCP server and evidence tools.
```

Any implementation must reverify version-sensitive details before coding.

---

## 13. Evidence freshness rule

For external documentation:

```text
CurrentFactValid =
  source_is_official
  ∧ source_checked_at implementation time
  ∧ version/protocol identity recorded where material
```

A year-old blog post about OpenClaw is not sufficient evidence for current wire behavior.

For KORPUS:

```text
CurrentImplementationEvidence =
  exact source SHA/digest
  ∧ exact test/verification artifact
```

---

## 14. Anti-authority rule

Never use a famous person, paper, standard or product documentation as a substitute for local reasoning.

Bad argument:

> “This is safe because a respected engineer advocates agents.”

Valid argument:

> “This action is safe enough for the declared class because authorization is exact, effect is idempotent, outcome ambiguity is reconciled, egress is bounded, and negative controls kill the relevant false-PASS classes.”

Authority references can explain why a design pattern is sensible; executable mechanisms must carry the actual claim.

---

## 15. Traceability map

| Principle/source | KORPUS × OpenClaw mechanism |
|---|---|
| OpenClaw Gateway control plane | route/session transport, never KORPUS authority |
| OpenClaw multi-agent | orchestration separation, not external assurance |
| OpenClaw nodes | bounded actuator/sensor model |
| MCP tools/resources | adapter boundary with local mapping |
| MCP security guidance | tool metadata treated as untrusted |
| NIST Zero Trust | no trust from network/device/session locality |
| AI RMF | risk/eval/governance lifecycle separation |
| RFC 9110 idempotency | capability-level retry semantics |
| Karpathy first-principles pedagogy | primitives -> mechanisms -> tests -> composition |
| Karpathy partial autonomy theme | risk-dependent autonomy ladder |
| control theory | closed-loop observe/act/verify |
| distributed systems | explicit ambiguous outcome + reconciliation |

---

## 16. Re-verification checklist before implementation

Record:

```text
OpenClaw root release
Gateway wire protocol version
@openclaw/gateway-client version
@openclaw/gateway-protocol version
node-host version if used
MCP config semantics and schema
tool policy semantics
KORPUS exact SHA/source digest
KORPUS MCP tool schema/digests
KORPUS release identity
```

Then mark each external claim:

```text
CONFIRMED
CHANGED_COMPATIBLE
CHANGED_BREAKING
UNKNOWN
```

No `UNKNOWN` material protocol assumption enters implementation silently.

---

## 17. Terminal principle

The theoretical standard is:

```text
understand mechanism
> state assumptions
> derive invariant
> bind invariant to observable
> design falsifying test
> implement minimal mechanism
> verify exact state
```

That is the intended meaning of “first-principles” in this proposal: not stylistic sophistication, but a chain from primitive state and constraints to executable, falsifiable system behavior.
