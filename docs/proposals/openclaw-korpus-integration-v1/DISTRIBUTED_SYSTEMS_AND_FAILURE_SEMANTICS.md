# Distributed Systems and Failure Semantics

**Status:** NORMATIVE THEORY FOR PROPOSAL v1

OpenClaw × KORPUS is a distributed system even when every process runs on one machine. Independent processes, transports, sessions, databases, external providers and devices create partial failure, stale state and uncertain outcomes.

---

## 1. Core distributed-systems law

```text
Request sent != request received
Request received != action executed
Action executed != response delivered
Response delivered != result verified
```

Any design that collapses these states will eventually misclassify an ambiguous external effect.

---

## 2. Failure domains

Partition failure by domain:

```text
F_channel
F_gateway
F_agent
F_mcp_transport
F_korpus_api
F_policy
F_database
F_object_store
F_external_provider
F_node
F_audit
F_delivery
```

A single visible “tool failed” message is insufficient because recovery depends on which domain failed and whether an effect may already have occurred.

---

## 3. Failure classes

### 3.1 Omission

Expected message/action never occurs.

### 3.2 Delay

Correct message/action occurs after deadline.

### 3.3 Duplication

Same logical request produces repeated execution.

### 3.4 Reordering

Events arrive in an order different from issuance.

### 3.5 Corruption

Payload/state is malformed or altered.

### 3.6 Byzantine/untrusted content

A component returns syntactically valid but malicious or misleading data.

For external tools/providers, semantic content is untrusted even if transport is authenticated.

---

## 4. Exactly-once is not assumed

The integration must not assume exactly-once network delivery or execution.

Instead aim for:

```text
at-least-once attempts
+ application idempotency
+ durable effect identity
+ reconciliation
=> at-most-one intended logical effect where contract supports it
```

This is a property to verify per capability, not a global transport promise.

---

## 5. Idempotency key construction

For side-effecting capability:

```text
K = H(
  subject_id,
  capability_id,
  capability_version,
  logical_resource,
  canonical_input_digest,
  workflow_effect_identity
)
```

Do not include volatile retry attempt number in the logical key.

Attempt identity is separate:

```text
attempt_id != idempotency_key
```

---

## 6. Reservation-before-effect

Preferred pattern for high-value effects:

```text
1. validate request
2. authorize exact binding
3. reserve logical effect key durably
4. execute provider action
5. record observed outcome
6. verify/reconcile
7. finalize state
```

This prevents two workers from independently executing the same logical effect when they race.

---

## 7. Effect ledger

Canonical effect ledger fields should include:

```text
effect_id
idempotency_key
subject_binding
capability_binding
resource_binding
input_digest
created_at
state
attempts[]
provider_receipt?
postcondition_evidence?
reconciliation_history[]
audit_reference
```

The ledger is evidence of workflow state, not proof that the external provider is truthful. Provider observations remain inputs to reconciliation.

---

## 8. Two-phase intuition without pretending to have distributed transactions

KORPUS cannot generally atomically commit with arbitrary external systems.

Therefore avoid language implying global ACID semantics.

A practical sequence is:

```text
LOCAL PREPARE
  reserve effect / audit intent

REMOTE EFFECT
  execute external call

LOCAL FINALIZE
  record known outcome or UNKNOWN
```

This is not two-phase commit unless the remote provider participates in an actual transaction protocol.

---

## 9. Ambiguous timeout example

Suppose OpenClaw requests a bounded external write through KORPUS.

Sequence:

```text
KORPUS -> provider: POST create/update
provider commits
provider -> KORPUS: response
network breaks before KORPUS reads response
```

Observed locally:

```text
timeout
```

True effect:

```text
committed
```

Therefore mapping timeout to failure and retrying can duplicate effect.

Required state:

```text
OUTCOME_UNKNOWN
```

until authoritative observation resolves it.

---

## 10. Reconciliation strategies

Choose based on provider semantics.

### 10.1 Read by provider receipt/id

Best when initial request deterministically names or returns stable effect identity.

### 10.2 Query by idempotency key

Best when provider persists the key.

### 10.3 Query by exact resource/version

Compare expected postcondition to actual resource.

### 10.4 Audit/event search

Use provider event log if authoritative enough.

### 10.5 Human/operator resolution

Required when no trustworthy observable exists.

Never use semantic similarity of natural-language state as a substitute for exact reconciliation when exact state matters.

---

## 11. Retry budget

Every adapter contract should declare:

```text
max_attempts
backoff_policy
retryable_failure_classes
requires_reconciliation_before_retry
request_deadline
attempt_timeout
```

No infinite autonomous retries.

---

## 12. Backoff

Backoff protects both local and remote systems from synchronized retry storms.

Use bounded exponential backoff with jitter where appropriate for transient network/service failures.

Do not apply retry/backoff to deterministic policy denial or schema invalidity.

---

## 13. Circuit breaking

Repeated provider failures may justify a circuit state:

```text
CLOSED -> OPEN -> HALF_OPEN -> CLOSED
```

This is an availability mechanism, not authorization.

An open circuit must not cause silent fallback to a less governed provider if the fallback changes evidence, data exposure or authority semantics.

---

## 14. Fallback theorem

Fallback is valid only if the substitute preserves every required contract.

```text
FallbackAllowed(A -> B) =
  SameAuthorityClass
  ∧ SameOrStricterEgress
  ∧ CompatibleEvidenceSemantics
  ∧ CompatibleEffectSemantics
  ∧ PolicyExplicitlyAllows(B)
```

Otherwise fallback is a new action requiring a new decision.

---

## 15. Version skew

OpenClaw Gateway, node host, protocol packages and KORPUS integration code can update independently.

Record:

```text
openclaw_release
gateway_protocol_version
client package version
node host version
MCP tool schema digest
KORPUS release/source digest
```

Compatibility should be tested on an explicit matrix rather than assumed from “latest”.

---

## 16. Schema evolution

For any remote/tool schema:

```text
compatible narrowing
compatible additive optional field
breaking removal
breaking type change
authority-widening semantic change
```

Authority-widening or ambiguous changes require disable/quarantine until reviewed.

A schema can be syntactically backward-compatible yet semantically dangerous.

Example:
- tool once read-only;
- same input schema now triggers write.

Therefore track effect semantics separately from JSON shape.

---

## 17. Causal ordering

For audit and effect reasoning, preserve causal identifiers:

```text
workflow_id
invocation_id
parent_invocation_id
attempt_id
idempotency_key
policy_decision_id
provider_request_id
```

Wall-clock timestamps alone cannot reliably prove event causality across machines.

---

## 18. Clock assumptions

Do not use timestamps as identity.

Use clocks for:
- freshness windows;
- deadlines;
- operational ordering hints;
- TTLs.

Use digests/versions/ids for exact state binding.

Clock skew should not cause an old artifact for another source subject to become accepted merely because its timestamp is recent.

---

## 19. Message delivery semantics

Channel delivery has its own state:

```text
READY_TO_DELIVER
DELIVERY_SENT
DELIVERY_ACCEPTED
DELIVERY_FAILED
DELIVERY_UNKNOWN
```

A KORPUS action may complete even if user-facing delivery fails.

Do not repeat the underlying side effect just to regenerate a delivery response.

---

## 20. Session split-brain

OpenClaw may have multiple agents/routes/sessions active.

Risks:
- two sessions mutate same resource concurrently;
- stale session continues after role revocation;
- duplicated messages trigger same workflow;
- user sends same command through two channels.

Mitigation:
- resource/version preconditions;
- durable logical idempotency;
- current KORPUS authorization per critical execution;
- explicit route/session identity in audit.

---

## 21. Node disconnect semantics

A node command can fail at several points:

```text
not routed
routed but not received
received but not started
started but interrupted
completed but response lost
```

Node adapter must classify which commands are:
- read-only;
- reversible;
- idempotent;
- ambiguous on disconnect.

Do not infer from command name alone.

---

## 22. Durable vs ephemeral state

Durable authoritative state:
- KORPUS policy/identity data;
- effect ledger;
- canonical audit;
- release identity;
- required evidence bindings.

Ephemeral operational state:
- model scratchpad;
- OpenClaw agent transient plan;
- WebSocket connection;
- in-memory retry counters unless persisted when needed.

A restart must not erase the information needed to prevent duplicate or unauthorized side effects.

---

## 23. Crash recovery

After process restart:

```text
scan PENDING / OUTCOME_UNKNOWN effects
 -> reconcile
 -> resume only safe workflows
```

Never assume all in-flight operations failed just because local process died.

---

## 24. Poison cases

Required distributed-failure tests:

```text
D01 duplicate inbound channel message
D02 duplicate MCP call
D03 response lost after provider commit
D04 KORPUS crash after remote effect before local finalize
D05 OpenClaw Gateway restart mid-workflow
D06 node disconnect after command starts
D07 provider returns success but postcondition absent
D08 provider returns error but effect exists
D09 stale tool schema after OpenClaw update
D10 two sessions race same resource
D11 clock skew on evidence freshness
D12 delayed old response arrives after retry
D13 audit write unavailable after effect
D14 route delivery fails after successful effect
```

Every case must produce a named state, not generic “unexpected error”.

---

## 25. Consistency target

Not every subsystem requires the same consistency model.

Examples:
- authorization: current canonical decision required;
- audit: strong enough ordering/binding for reconstruction;
- telemetry: eventual consistency acceptable;
- chat presence indicators: best-effort acceptable;
- side-effect ledger: durable exact identity required.

Choosing consistency per property avoids both overengineering and unsafe under-specification.

---

## 26. HTTP semantics

RFC 9110 defines safe and idempotent HTTP method semantics and explains why idempotent requests are retryable after some communication failures. KORPUS must still reason at the logical capability level because an application can expose nontrivial semantics behind generic methods.

Reference:
- https://www.rfc-editor.org/rfc/rfc9110.html

---

## 27. Operational SLOs vs correctness

Latency and availability SLOs matter, but:

```text
late correct refusal > fast unauthorized execution
```

for protected operations.

Optimization priority:
1. correctness/integrity;
2. bounded availability;
3. performance.

---

## 28. Terminal principle

The integration must be designed for the world where:
- messages duplicate;
- connections break;
- processes restart;
- responses arrive late;
- remote schemas change;
- external effects happen before local certainty.

A system that is correct only when every component responds once, immediately and in order is not a distributed-systems design; it is a demo-path assumption.
