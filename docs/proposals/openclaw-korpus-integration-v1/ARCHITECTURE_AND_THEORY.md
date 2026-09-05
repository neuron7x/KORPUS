# Architecture and Theory

## 1. System decomposition

KORPUS and OpenClaw solve different classes of problems and must remain separated by authority.

### OpenClaw responsibilities

OpenClaw is used as an external orchestration and interaction layer:
- channel connectivity;
- session routing;
- agent selection;
- scheduled or event-driven workflow initiation;
- node/device transport;
- bounded invocation of declared KORPUS capabilities;
- human-facing continuity across channels.

### KORPUS responsibilities

KORPUS remains responsible for:
- subject identity interpretation;
- account and entitlement state;
- corpus/security authorization;
- retrieval admission;
- evidence validity and provenance;
- contradiction and abstention logic;
- effect authorization;
- canonical audit;
- release/runtime identity;
- production authority.

The distinction is architectural, not cosmetic. If OpenClaw is allowed to decide KORPUS authorization, the system gains a second authority plane and loses the ability to reason locally about access, evidence and audit invariants.

## 2. Authority theorem

Let:
- `S` be the KORPUS subject;
- `C` be a locally registered capability;
- `I` be normalized input;
- `P` be the canonical KORPUS policy state;
- `E` be the external-effect preconditions;
- `R` be the adapter result;
- `V` be the evidence/audit validity state.

Execution is admissible iff:

```text
Execute(S,C,I,P,E) =
  ExactCapability(C)
  ∧ Authenticated(S)
  ∧ Authorized(P,S,C,I)
  ∧ InputValid(C,I)
  ∧ EgressAllowed(P,C,I)
  ∧ EffectSafe(C,I,E)
```

Critical returnability is distinct:

```text
Return(R,V) =
  OutputValid(C,R)
  ∧ EvidenceValid(C,R,V)
  ∧ AuditCommitted(C,R,V)
```

This separation prevents four common category errors:

```text
CanCall     != MayCall
WasCalled   != Succeeded
Succeeded   != Verified
Verified    != AuthorizedForAnotherSubject
```

## 3. Control-plane separation

OpenClaw Gateway may be a control plane for OpenClaw sessions, channels and nodes. It is not the KORPUS control plane for protected operations.

```text
OpenClaw control plane:
  channel -> session -> agent -> tool transport

KORPUS control plane:
  identity -> policy -> capability -> evidence/effect -> audit
```

The two planes intersect at an explicit adapter boundary.

## 4. Identity model

A channel sender, OpenClaw agent id, OpenClaw session key, Gateway token and KORPUS subject are different identities.

The integration must never infer:

```text
OpenClawSession == KorpusSubject
ChannelSender    == KorpusSubject
GatewayToken     == KorpusAuthorization
AgentName        == SecurityRole
```

Identity binding requires an explicit KORPUS-controlled mapping or KORPUS-issued credential. The adapter must carry the minimum subject context required for KORPUS to re-authorize every protected operation.

### Required identity properties

For every KORPUS invocation:
- authenticated subject id;
- KORPUS account/principal reference;
- applicable roles/clearance/corpora/compartments resolved by KORPUS, not trusted from OpenClaw payload;
- request correlation id;
- OpenClaw session metadata retained only as untrusted/audit context unless separately verified.

## 5. Capability model

OpenClaw should not receive an unrestricted generic `execute` capability. Each operation must be a named, versioned capability with a closed contract.

A capability contains:

```text
CapabilitySpec = {
  id,
  version,
  effect_class,
  authorization_action,
  logical_resource_binding,
  input_schema_digest,
  output_schema_digest,
  egress_policy,
  evidence_profile,
  timeout_policy,
  retry_policy,
  idempotency_policy,
  adapter_binding
}
```

Discovery may be broad; execution is narrow.

```text
Discovered(tool) != RegisteredCapability(tool)
RegisteredCapability(tool) != AuthorizedInvocation(tool)
```

## 6. MCP placement

KORPUS already has an MCP server backed by the existing KORPUS API. This is the preferred first integration boundary because it preserves the current authorization and evidence path.

The initial relation is:

```text
OpenClaw MCP client/runtime
        |
        v
KORPUS MCP server
        |
        v
KORPUS API
        |
        v
canonical identity/policy/retrieval/evidence/audit
```

MCP metadata and descriptions are not privileged instructions. Tool output is data and must remain subject to local validation.

## 7. OpenClaw Gateway placement

OpenClaw's Gateway may provide:
- durable session routing;
- channel connections;
- node transport;
- operator UI/CLI access;
- workflow triggering.

KORPUS must not depend on OpenClaw Gateway state as evidence of KORPUS authorization. Gateway state is operational evidence about OpenClaw, not security evidence about KORPUS.

## 8. Agent topology

The default topology should minimize authority and coordination cost.

### Recommended baseline

One OpenClaw orchestration agent can:
1. receive a user message;
2. classify the requested workflow locally;
3. call `korpus_grounds` when the question is factual/evidence-sensitive;
4. call `korpus_ask` when grounds exist;
5. compose a user-facing response;
6. call `korpus_verify` before presenting factual text where required;
7. return the result to the originating channel.

### Multi-agent use

Additional agents are justified only when they provide one of:
- independent structural verification;
- privilege separation;
- domain/tool isolation;
- parallel execution with measurable latency benefit.

Multi-agent decomposition without one of those benefits adds coordination state and attack surface.

## 9. Data-class boundaries

Every OpenClaw-facing KORPUS capability should declare a maximum material class.

Suggested classes:

```text
PUBLIC_METADATA
AUTHORIZED_EXTRACT
AUTHORIZED_EVIDENCE
RESTRICTED_DERIVED
SIDE_EFFECT_RECEIPT
SECRET_NEVER_EXPORTED
```

The adapter applies a material ceiling before transport. Secrets, unrestricted corpus dumps and credentials are never returned merely because the caller is an OpenClaw agent.

## 10. Read-path semantics

The read/evidence path is the lowest-risk integration and should be implemented first.

```text
User/channel
 -> OpenClaw session
 -> KORPUS grounds
 -> KORPUS ask
 -> citations + hashes + release identity
 -> agent composition
 -> KORPUS verify
 -> channel response
```

The model/agent may summarize only within the declared output contract. KORPUS evidence remains the source of factual authority.

## 11. Side-effect semantics

Writes require a different model from reads.

For a side effect `a`, execution must establish:

```text
EffectAdmissible(a) =
  Authorized(a)
  ∧ IdempotencyBound(a)
  ∧ ResourceBound(a)
  ∧ PreconditionsCurrent(a)
  ∧ CompensationSemanticsKnown(a)
```

Outcomes are represented explicitly:

```text
PENDING
COMMITTED
FAILED_KNOWN_NO_EFFECT
OUTCOME_UNKNOWN
RECONCILED
```

`OUTCOME_UNKNOWN` is not success and must block unsafe blind retry.

## 12. Device and node semantics

OpenClaw nodes may expose device-local capabilities such as computer control or device sensors. Node availability does not grant KORPUS authorization.

A node action involving KORPUS-protected data must still pass the KORPUS capability boundary. In particular:
- a device should not receive a broader corpus view than the subject can access;
- screenshots/files must be treated as data with explicit egress classification;
- node execution must not become a hidden path around KORPUS policy.

## 13. Channel semantics

A messaging channel is a transport surface. It is not a trust root.

Threats include:
- account takeover;
- sender spoofing or misbinding;
- group-chat context leakage;
- accidental cross-account routing;
- forwarding of restricted outputs.

Therefore channel-to-KORPUS workflows must bind KORPUS identity explicitly and minimize output material to the channel context.

## 14. Audit model

KORPUS audit is authoritative for KORPUS actions. OpenClaw logs add orchestration context.

A KORPUS audit record should be capable of referencing:
- KORPUS subject;
- capability id/version;
- policy decision id;
- normalized input digest;
- effect/adapter outcome;
- evidence/output digest;
- KORPUS release/runtime identity;
- OpenClaw correlation/session id as non-authoritative context.

The reverse must not occur: OpenClaw session history cannot prove that KORPUS policy permitted an action.

## 15. Failure semantics

The boundary must distinguish:

```text
TRANSPORT_FAILURE
AUTHENTICATION_FAILURE
AUTHORIZATION_DENIED
INPUT_INVALID
EGRESS_DENIED
EFFECT_PRECONDITION_FAILED
ADAPTER_FAILURE
OUTPUT_INVALID
EVIDENCE_INVALID
AUDIT_COMMIT_FAILURE
OUTCOME_UNKNOWN
```

Do not collapse these into a generic agent-visible success/failure boolean. Correct recovery depends on cause.

## 16. Epistemic model

Three layers of truth must remain distinct:

1. **OpenClaw operational truth** — session/channel/node state.
2. **KORPUS execution truth** — authorization, effect and audit state.
3. **KORPUS factual truth** — evidence admissibility for claims.

A statement from layer 1 cannot substitute for evidence in layer 2 or 3.

## 17. Release invariants

The integration must preserve existing KORPUS invariants:
- authorization before retrieval/materialization/model egress;
- entitlement does not widen security scope;
- conversation history is context, not evidence;
- only approved temporally valid evidence is admissible;
- unsupported or contradictory factual output abstains;
- audit/release identity remain canonical;
- no external adapter creates a parallel truth store.

## 18. Architectural conclusion

OpenClaw is valuable precisely when it remains outside the KORPUS authority kernel. It should increase reachability, continuity, device access and workflow automation without increasing the set of entities that can authorize KORPUS operations.

The target property is therefore:

```text
More interaction surfaces
+ more automation
+ more bounded capabilities
- no new authority plane
- no weaker evidence boundary
- no hidden side-effect path
```
