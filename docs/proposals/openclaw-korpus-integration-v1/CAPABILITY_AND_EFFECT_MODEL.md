# Capability and Effect Model

## 1. Why capabilities are required

OpenClaw can orchestrate many tools and channels. KORPUS must not expose that breadth as ambient authority. Every KORPUS-facing operation is represented as a local capability with explicit semantics.

The unit of authorization is not “the agent”. It is:

```text
(subject, capability, version, resource, normalized input, current policy state)
```

## 2. Capability classes

### READ_LOCAL
Reads local KORPUS state without external provider effects.

Examples:
- health/readiness;
- authorized account/corpus metadata;
- release identity;
- evidence-ground checks.

### READ_REMOTE
Reads an external provider through KORPUS-controlled egress.

Requires:
- provider allowlist;
- outbound material ceiling;
- timeout/retry policy;
- response validation.

### WRITE_REMOTE
Creates or changes external state.

Requires:
- explicit resource binding;
- idempotency;
- effect receipt;
- reconciliation semantics.

### TRANSACTIONAL_SIDE_EFFECT
A workflow with multiple dependent effects or compensation requirements.

Requires:
- effect graph;
- finite acyclic compensation relation;
- explicit partial-failure semantics;
- no claim of atomicity unless actually provided by the underlying system.

### PRIVILEGED_ADMIN
Changes KORPUS-sensitive configuration, security state, release state or privileged corpus state.

Default posture:
- not exposed to OpenClaw in v1;
- requires explicit Owner-governed enablement.

## 3. Capability lifecycle

```text
DISCOVERED_UNTRUSTED
    -> REVIEWED
    -> LOCALLY_REGISTERED
    -> TESTED
    -> ENABLED_FOR_SCOPE
    -> QUARANTINED / DISABLED / RETIRED
```

No discovered remote tool executes directly.

## 4. Local registry

The local registry owns semantic identity. A remote provider's tool name is only a provider reference.

Example:

```yaml
id: korpus.openclaw.channel.reply
version: 1
provider:
  kind: openclaw_gateway
  operation: conversations_send
provider_schema_sha256: <digest>
effect_class: WRITE_REMOTE
authorization_action: channel:reply
resource_binding: originating_route
egress_policy: authorized_response_only
idempotency: required
output_evidence: delivery_receipt
```

If OpenClaw renames or changes the remote tool, the local capability does not silently inherit new semantics.

## 5. Resource binding

Authorization must bind the logical resource before execution.

Examples:
- KORPUS conversation id;
- corpus id;
- document/version id;
- originating OpenClaw route/account/thread;
- registered node id;
- external task/work item id.

Resource resolution occurs before effect execution. Caller-supplied resource metadata is normalized and revalidated.

## 6. Input canonicalization

Idempotency, audit and authorization depend on stable input identity.

Canonicalization must:
- validate types;
- remove non-semantic representation differences;
- reject unknown authority-bearing fields;
- normalize resource identifiers;
- serialize deterministically;
- hash canonical bytes.

```text
canonical_input_digest = SHA256(CanonicalJSON(validated_input))
```

## 7. Effect reservation

For side effects, KORPUS reserves an effect record before dispatch.

Suggested state:

```text
EffectRecord = {
  effect_id,
  invocation_id,
  subject_id,
  capability_id,
  capability_version,
  logical_resource,
  canonical_input_digest,
  idempotency_key,
  state,
  provider_reference?,
  request_digest?,
  response_digest?,
  created_at,
  updated_at
}
```

## 8. Effect state machine

```text
NEW
 -> PENDING
 -> COMMITTED
 -> FAILED_KNOWN_NO_EFFECT
 -> OUTCOME_UNKNOWN
 -> RECONCILING
 -> RECONCILED_COMMITTED
 -> RECONCILED_NO_EFFECT
```

Illegal transitions fail closed.

### Meaning

- `PENDING`: dispatch initiated; final outcome not yet established.
- `COMMITTED`: provider effect observed and validated.
- `FAILED_KNOWN_NO_EFFECT`: failure proved before effect occurred.
- `OUTCOME_UNKNOWN`: the system cannot determine whether effect occurred.
- `RECONCILING`: explicit observation/recovery in progress.
- `RECONCILED_COMMITTED`: later observation proves effect happened.
- `RECONCILED_NO_EFFECT`: later observation proves effect did not happen.

## 9. Idempotency law

A side effect must not rely on agent memory to avoid duplication.

```text
SameLogicalEffect(a,b) => SameIdempotencyIdentity(a,b)
```

Recommended key binding:

```text
H(
  subject_id,
  capability_id,
  capability_version,
  logical_resource,
  canonical_input_digest,
  client_operation_id
)
```

A retry with the same logical identity returns/continues the existing effect record rather than dispatching a second effect.

## 10. Retry law

Reads may use bounded retry when semantically safe.

Writes obey:

```text
RetryAllowed =
  ProvenIdempotent
  OR ProvenNoEffectOccurred
  OR ExplicitReconciliationAuthorizesRetry
```

Timeout alone never proves no effect.

## 11. Compensation

Compensation is not rollback unless the underlying operation actually has inverse semantics.

For compensation graph `G=(V,E)` require:
- finite `V`;
- acyclic compensation dependency relation;
- every compensating action independently authorized;
- explicit statement of what compensation can and cannot restore.

Acyclicity proves structural termination of the compensation ordering. It does not prove:
- compensation success;
- atomicity;
- semantic inversion;
- restoration of all external consequences.

## 12. Evidence for effects

A successful side effect requires evidence appropriate to its class.

Examples:
- provider receipt id;
- returned object/version id;
- post-condition observation;
- immutable response digest;
- KORPUS audit reference.

`HTTP 200` alone is insufficient when the logical post-condition can be independently checked.

## 13. OpenClaw-specific capability families

Potential families, introduced incrementally:

### `openclaw.channel.*`
- list/read permitted routed conversations;
- send response to the bound originating route;
- never arbitrary destination by default.

### `openclaw.session.*`
- inspect session status;
- create bounded task/session only with declared purpose and policy;
- session identity remains non-authoritative for KORPUS.

### `openclaw.node.*`
- status/capability discovery;
- bounded device actions;
- restricted-data egress prohibited unless explicitly admitted.

### `openclaw.automation.*`
- create/update scheduled workflows only when policy allows;
- schedule definition is an effect and requires audit/idempotency.

### `korpus.evidence.*`
Existing read path:
- grounds;
- ask;
- quote;
- verify.

## 14. Capability minimization matrix

| Workflow | Minimum capability | Effect class | Default v1 |
|---|---|---:|---|
| Ask KORPUS from Telegram | `korpus_ask` | READ_LOCAL/API read | ENABLE |
| Check whether grounds exist | `korpus_grounds` | READ_LOCAL/API read | ENABLE |
| Verify citation | `korpus_quote` | READ_LOCAL/API read | ENABLE |
| Verify agent draft | `korpus_verify` | PURE/READ | ENABLE |
| Reply to same OpenClaw route | `openclaw.channel.reply` | WRITE_REMOTE | LATER / guarded |
| Arbitrary channel send | broad messaging write | WRITE_REMOTE | DENY by default |
| Run shell on production host | generic exec | PRIVILEGED_ADMIN | DENY |
| Modify KORPUS policy | admin mutation | PRIVILEGED_ADMIN | DENY |
| Sign release | Owner authority | PRIVILEGED_ADMIN | NEVER delegated |

## 15. Dynamic discovery

OpenClaw may discover tools dynamically. KORPUS may inspect discovery metadata, but execution remains gated by local mapping.

```text
Discovery -> candidate metadata
Candidate metadata -> review/schema digest/effect classification
Only then -> local capability
```

This preserves flexibility without runtime privilege expansion.

## 16. Versioning

Capability version changes when any behavior relevant to authorization/effect/evidence changes:
- accepted inputs;
- logical resource semantics;
- side-effect class;
- provider operation;
- output/evidence contract;
- retry/idempotency behavior.

Cosmetic description changes need not create a new logical version if schema/semantics remain identical, but provider metadata digest changes are still observable.

## 17. Result model

A governed result should separate execution and returnability:

```json
{
  "invocation_id": "...",
  "capability": "...",
  "version": 1,
  "authorization": "ALLOW",
  "execution": "COMMITTED",
  "output_valid": true,
  "evidence_valid": true,
  "audit_committed": true,
  "returnable": true
}
```

No single `success: true` field should collapse these states.

## 18. Practical consequence

OpenClaw can become a broad orchestration substrate without receiving broad KORPUS authority. New functionality is added by registering a small capability and proving its boundary, not by widening an agent's generic permissions.
