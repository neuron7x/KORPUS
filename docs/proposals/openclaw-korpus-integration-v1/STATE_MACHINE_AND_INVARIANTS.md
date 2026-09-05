# Execution State Machine and Killable Invariants

**Status:** NORMATIVE THEORY FOR PROPOSAL v1

This document converts the integration from a collection of API calls into an explicit state machine whose illegal transitions are testable.

---

## 1. Why a state machine is required

An agentic workflow is not safe because each individual call has a reasonable function name. Safety depends on **ordering, binding, and transition semantics**.

A state machine makes the following questions executable:

- was authorization evaluated before materialization/execution?
- did the exact resource stay bound across retries?
- did a transport failure happen before or after an external side effect?
- did the verifier inspect the exact result that was returned?
- was the result delivered only to the bound route?

---

## 2. Invocation state machine

Canonical high-level states:

```text
RECEIVED
  -> ROUTE_BOUND
  -> SUBJECT_BOUND
  -> CAPABILITY_RESOLVED
  -> RESOURCE_BOUND
  -> AUTHORIZED
  -> INPUT_VALIDATED
  -> EGRESS_VALIDATED
  -> EFFECT_GUARDED
  -> EXECUTING
  -> EXECUTION_OBSERVED
  -> OUTPUT_VALIDATED
  -> EVIDENCE_VALIDATED
  -> AUDIT_COMMITTED
  -> DELIVERY_AUTHORIZED
  -> COMPLETED
```

Failure/terminal states:

```text
REFUSED_IDENTITY
REFUSED_CAPABILITY
REFUSED_RESOURCE
REFUSED_POLICY
REFUSED_INPUT
REFUSED_EGRESS
REFUSED_EFFECT
FAILED_KNOWN_NO_EFFECT
OUTCOME_UNKNOWN
RECONCILIATION_REQUIRED
VERIFICATION_FAILED
AUDIT_FAILED
DELIVERY_REFUSED
ABSTAINED
CANCELLED
```

---

## 3. Legal transition rule

For transition `s_i -> s_j`, define:

```text
Legal(s_i, s_j) =
  transition_declared
  ∧ preconditions_satisfied
  ∧ bindings_preserved
  ∧ no higher-priority refusal predicate
```

Unknown precondition:

```text
UNKNOWN -> transition denied
```

unless that transition is explicitly a discovery/read step designed to reduce the unknown without causing protected effect.

---

## 4. Binding tuple

Every invocation carries an immutable logical binding tuple:

```text
B = H(
  invocation_id,
  korpus_subject_id,
  capability_id,
  capability_version,
  logical_resource,
  canonical_input_digest,
  release_identity,
  route_binding
)
```

For effectful actions add:

```text
idempotency_key
```

A retry or continuation that changes any authority-relevant field is a new logical invocation unless policy explicitly defines a safe continuation relation.

---

## 5. Binding preservation invariant

```text
I_BIND:
  B_authorized == B_executed == B_audited
```

For returned critical result:

```text
B_audited == B_delivered
```

Negative control:
- authorize resource A;
- substitute resource B immediately before adapter execution;
- expected: FAIL.

---

## 6. Identity invariant

```text
I_IDENTITY:
  OpenClaw route/account identity cannot directly instantiate
  a privileged KORPUS subject without explicit binding.
```

Required properties:
- binding source known;
- binding versioned/revocable;
- ambiguous match refused;
- group/channel identity cannot silently become an individual principal;
- subject changes invalidate stale authorization.

---

## 7. Complete mediation invariant

For each protected action:

```text
I_MEDIATION:
  every logical execution crosses KORPUS authorization.
```

No alternate path may exist through:
- direct MCP server call bypassing KORPUS API/policy;
- node command wrapper;
- channel-specific plugin;
- “trusted” admin metadata;
- cached previous allow decision beyond its declared validity.

---

## 8. Capability exactness invariant

```text
I_CAPABILITY:
  requested capability == locally registered exact capability version
```

Remote discovery may propose candidate metadata. Execution requires local normalization and exact resolution.

Forbidden:

```text
contains("delete") -> authorize generic delete
prefix match -> broader capability
provider description -> local permission
schema-compatible unknown version -> automatic promotion
```

---

## 9. Resource exactness invariant

Authorization must be over a concrete enough resource identity.

```text
I_RESOURCE:
  Authorize(subject, capability, resource_bound)
```

not:

```text
Authorize(subject, capability, "some resource chosen later")
```

If provider chooses the final object dynamically, the capability contract must explicitly model that selection and constrain admissible result/resource class.

---

## 10. Evidence invariant

For evidence-returning KORPUS tools:

```text
I_EVIDENCE:
  factual claim admitted by KORPUS
  -> exact source-bound evidence exists
```

For OpenClaw-composed prose:

```text
I_COMPOSITION:
  critical sentence returned as KORPUS-grounded
  -> korpus_verify or equivalent support check passes
```

Session history cannot satisfy this invariant by itself.

---

## 11. Egress invariant

```text
I_EGRESS:
  material leaving KORPUS boundary
  ⊆ material authorized for destination/provider/channel
```

Destination is part of the decision.

Same subject + same data + different destination may yield different authorization.

---

## 12. Side-effect invariant

```text
I_EFFECT:
  side effect may execute only after exact authority,
  input, egress and effect guards are satisfied.
```

Effect class cannot be inferred solely from transport verb.

---

## 13. Idempotency invariant

For an operation declared logically idempotent:

```text
I_IDEMPOTENCY:
  N replays with identical logical effect binding
  -> at most one intended logical effect
```

The system may produce multiple audit events, attempts or transport exchanges while still preserving one logical effect.

---

## 14. Unknown-outcome invariant

```text
I_UNKNOWN:
  cannot prove no-effect
  AND cannot prove commit
  -> OUTCOME_UNKNOWN
```

Forbidden mapping:

```text
transport timeout -> FAILED
transport timeout -> SUCCESS
```

without state evidence.

---

## 15. Reconciliation invariant

```text
I_RECONCILE:
  OUTCOME_UNKNOWN
  -> reconciliation before retry or success return
```

Reconciliation must query an authoritative observable when one exists.

If no reliable observable exists, escalate/manual intervention rather than guessing.

---

## 16. Compensation invariant

A compensation is a new authorized action, not magical rollback.

```text
Compensate(a) != Inverse(a)
```

unless semantic inverse is explicitly proven.

Compensation requires:
- own capability id;
- own authorization;
- own resource binding;
- own effect state;
- own audit;
- bounded recursion/acyclic compensation graph.

---

## 17. Audit invariant

```text
I_AUDIT:
  critical execution returnable
  -> canonical audit commit succeeded
```

Audit should bind at minimum:

```text
subject
capability/version
resource
input digest
policy decision reference
route identity
execution/effect state
output/evidence digests
release/runtime identity
```

OpenClaw session logs are useful context but not a replacement.

---

## 18. Delivery invariant

```text
I_DELIVERY:
  valid internal result
  != automatically deliverable result
```

Before delivery validate:
- route still bound;
- route corresponds to intended peer/thread;
- channel permitted for data class;
- no session cross-talk;
- result still current enough for its semantics.

---

## 19. Release invariant

```text
I_RELEASE:
  integration execution evidence
  must name exact KORPUS source/release/runtime identity
```

A passing test against old KORPUS state cannot authorize a later state automatically.

OpenClaw version/protocol identity must also be recorded for compatibility-sensitive evidence.

---

## 20. Route state machine

Route lifecycle:

```text
DISCOVERED
 -> AUTHENTICATED_OPENCLAW_ROUTE
 -> KORPUS_SUBJECT_BINDING_PENDING
 -> KORPUS_SUBJECT_BOUND
 -> ACTIVE
 -> STALE / REVOKED / EXPIRED
```

A route can remain operationally connected while its KORPUS subject binding is revoked.

Therefore:

```text
GatewayConnected != KorpusAuthorized
```

---

## 21. Node state machine

```text
UNPAIRED
 -> PAIRING_PENDING
 -> PAIRED
 -> COMMAND_SURFACE_OBSERVED
 -> POLICY_MAPPED
 -> ACTIVE_BOUNDED
 -> QUARANTINED / REVOKED / OFFLINE
```

Node commands are not executable for KORPUS-protected workflows at `PAIRED` alone.

`POLICY_MAPPED` requires local command/capability classification.

---

## 22. MCP tool state machine

For discovered external/OpenClaw-side MCP tool metadata:

```text
DISCOVERED_UNTRUSTED
 -> SCHEMA_OBSERVED
 -> LOCAL_MAPPING_PROPOSED
 -> LOCAL_MAPPING_VERIFIED
 -> ENABLED_BOUNDED
 -> QUARANTINED / DISABLED
```

Schema drift transition:

```text
ENABLED_BOUNDED
 + incompatible schema digest
 -> QUARANTINED
```

Never:

```text
schema changed -> silently accept broader capability
```

---

## 23. Session continuity invariant

Long-lived OpenClaw sessions can outlive:
- KORPUS role changes;
- release changes;
- corpus changes;
- node revocation;
- tool schema changes.

Therefore:

```text
I_SESSION:
  session continuity does not imply authority continuity.
```

Security-sensitive decisions must use current bounded state, not session-start assumptions.

---

## 24. Cancellation semantics

Cancellation is not proof that an external action stopped.

```text
CancelRequested
 != CancelConfirmed
 != NoEffect
```

For effectful action:
- record cancellation attempt;
- observe provider/action state;
- reconcile if outcome ambiguous.

---

## 25. Timeout semantics

Timeout classes:

```text
CONNECT_TIMEOUT      -> likely no request reached provider, but verify semantics
READ_TIMEOUT         -> provider may have executed
OVERALL_DEADLINE     -> workflow stopped waiting; effect may persist
NODE_DISCONNECT      -> node command outcome may be unknown
```

The adapter contract must specify which timeout classes can produce ambiguous effects.

---

## 26. Concurrency invariants

For concurrent operations on same logical resource:

```text
I_CONCURRENCY:
  interleaving must not bypass preconditions or duplicate logical effect.
```

Use where appropriate:
- optimistic version precondition;
- row/object lock;
- compare-and-swap;
- idempotency reservation;
- serialized resource actor.

The correct mechanism depends on resource semantics.

---

## 27. Monotonic safety state

Certain safety facts should be monotonic within an invocation.

Examples:
- once authorization fails, the same invocation cannot later become authorized without a new policy/state decision;
- once evidence is found stale, it cannot become current by relabeling;
- once effect outcome is unknown, success cannot be returned until reconciliation resolves it.

---

## 28. State-machine negative controls

Minimum poison suite:

```text
S01 skip SUBJECT_BOUND -> expect refusal
S02 change capability version after authorization -> fail
S03 change resource after authorization -> fail
S04 bypass egress check -> mutation test killed
S05 adapter returns malformed output -> fail
S06 missing evidence where required -> fail
S07 audit commit failure -> critical result not returned
S08 timeout after possible side effect -> OUTCOME_UNKNOWN
S09 blind retry OUTCOME_UNKNOWN -> prevented
S10 wrong route delivery -> refused
S11 stale OpenClaw tool schema -> quarantined
S12 revoked node reused by long session -> refused
S13 old KORPUS release evidence reused -> fail
S14 OpenClaw token valid but KORPUS policy deny -> fail
S15 channel user spoofing claimed KORPUS subject -> fail
```

---

## 29. Machine-readable future contract

This document should ultimately compile into executable declarative state-machine artifacts or tests.

Suggested future schema concepts:

```text
states
terminal_states
legal_transitions
transition_preconditions
binding_fields
unknown_policy
retry_policy
reconciliation_policy
required_evidence
required_audit
negative_controls
```

Documentation alone is not sufficient closure.

---

## 30. Terminal theorem

A workflow is valid only when the sequence is valid, not merely the endpoints.

```text
ValidWorkflow(trace) =
  every transition legal
  ∧ every binding preserved
  ∧ every required verifier executed
  ∧ every critical output auditable
```

Therefore:

```text
CorrectResult from IllegalTrace = INVALID
```

Accidental success does not validate the mechanism.
