# Information-Flow, Data Classification, and Privacy Model

**Status:** NORMATIVE THEORY FOR PROPOSAL v1

OpenClaw increases the number of possible routes through which information can move: channels, agents, models, MCP servers, nodes, plugins and external APIs. Therefore the integration must reason not only about whether an action is authorized, but also **where each byte may travel**.

---

## 1. Core theorem

```text
ActionAuthorized(subject, action, resource)
!=
DataAuthorizedForDestination(subject, data, destination)
```

An operation can be internally authorized while its result is not permitted to leave through a particular channel, model provider, node or plugin.

---

## 2. Information-flow graph

Model the system as directed graph:

```text
G = (V, E)
```

Vertices may include:

```text
KORPUS API
KORPUS DB
KORPUS object store
KORPUS MCP
OpenClaw Gateway
OpenClaw agent runtime
model provider
channel provider
node
external MCP server
external HTTP API
operator UI
```

An edge means information may cross from one component to another.

Every edge involving protected material needs a policy reason.

---

## 3. Data classes

At minimum classify data into:

```text
PUBLIC
INTERNAL
RESTRICTED
SECRET_OR_CREDENTIAL
AUDIT_SENSITIVE
PERSONAL_OR_ACCOUNT
DERIVED_OPERATIONAL
```

The exact production taxonomy should reuse KORPUS canonical classifications where possible rather than inventing a second classification system.

---

## 4. Destination classes

```text
LOCAL_KORPUS
LOCAL_OPENCLAW
APPROVED_MODEL_PROVIDER
APPROVED_CHANNEL
APPROVED_NODE
APPROVED_EXTERNAL_SERVICE
UNTRUSTED_REMOTE
```

A destination class is not inferred from DNS name alone; it is deployment/configuration identity.

---

## 5. Flow decision

For data item `d` and destination `z`:

```text
FlowAllowed(d, z, x) =
  SubjectAuthorized(d, x)
  ∧ DestinationApproved(z, class(d))
  ∧ PurposeCompatible(d, z, x)
  ∧ DataMinimized(d)
  ∧ NoSecretLeak(d)
  ∧ CurrentPolicyAllows(x)
```

Unknown destination identity -> no protected flow.

---

## 6. Data minimization

Let:

```text
D_need = minimum data necessary for admitted task
D_send = actual data emitted
```

Required:

```text
D_send ⊆ D_need ∩ D_authorized
```

Optimization:

```text
minimize |D_send|
```

subject to correct task completion.

---

## 7. Query vs corpus material

A user question and retrieved corpus material are different classes.

The query may contain sensitive context even if no corpus text is sent.

Therefore model egress policy must separately consider:
- free-text user query;
- retrieved source text;
- citations;
- metadata;
- conversation context.

---

## 8. Session history

OpenClaw session history is operational context.

It must not automatically become:
- KORPUS evidence;
- KORPUS authorization;
- a permanent copy of restricted corpus material.

Retention should be explicit per deployment/channel.

---

## 9. Channel privacy

Channel risk differs by provider and conversation type.

Examples:
- direct message;
- private group;
- large group;
- public channel;
- bot-mediated thread.

Delivery policy should use exact route type and data class.

A result valid for a direct channel may be forbidden in a group route.

---

## 10. Group-context rule

Group participation creates ambiguity about audience.

Therefore:

```text
GroupMessageFromAuthorizedUser
!=
AuthorizedToDiscloseToGroup
```

The audience set matters.

---

## 11. Node privacy

A paired node may have:
- screen;
- camera;
- filesystem;
- notifications;
- local MCP servers;
- system commands.

Pairing proves device relationship to OpenClaw, not permission for every KORPUS data class.

Use a node data ceiling:

```text
NodeDataCeiling(node_id) = max allowed KORPUS class
```

and command allowlist.

---

## 12. Model provider boundary

Before sending any material to an external model:

```text
model provider configured
∧ egress policy allows data class
∧ quantity within material ceiling
∧ request purpose allowed
```

The model response remains generated text, not factual authority.

---

## 13. External MCP server boundary

An external MCP server can receive tool inputs and return arbitrary data.

Therefore:
- input data minimization;
- server identity binding;
- tool schema digest;
- egress class;
- response treated as untrusted until validated.

Do not expose KORPUS corpus material to an unrelated MCP tool merely because it is available to the same OpenClaw agent.

---

## 14. Tool composition hazard

Agent frameworks make compositional exfiltration easy:

```text
KORPUS read tool -> model context -> unrelated send/upload tool
```

Each individual tool may be authorized in isolation while the composition is not.

Therefore policy must reason about flow across the workflow, not just tool-level permission.

---

## 15. Taint-style conceptual model

Treat protected material as carrying labels:

```text
label(d) = {
  classification,
  subject_scope,
  corpus_scope,
  purpose,
  source,
  expiry?
}
```

A transformation may narrow or preserve labels, but cannot arbitrarily erase them.

Example:
- summarization does not automatically make restricted source public;
- hashing may reduce content exposure but still be sensitive if linkable;
- metadata may reveal protected source existence.

---

## 16. Derived data

Derived content inherits relevant restrictions unless proven otherwise.

```text
classification(derived)
>= required restrictions of source material
```

Do not assume “model-generated” means unclassified.

---

## 17. Citation leakage

Citation fields can leak:
- source title;
- URI;
- page;
- section;
- document existence;
- revision;
- authority classification.

Therefore citation presentation is also an egress decision.

---

## 18. Logs

Never log:
- bearer tokens;
- secret env values;
- private key material;
- full restricted corpus payload by default.

Operational logs should prefer digests, ids and bounded metadata.

Canonical audit may contain sensitive identifiers and therefore has its own access policy.

---

## 19. Secret rule

```text
Secret -> model context = forbidden by default
Secret -> channel = forbidden
Secret -> generic tool output = forbidden
```

Secrets should be passed through dedicated secret/config mechanisms invisible to model text whenever possible.

---

## 20. Purpose binding

The fact that subject may read a resource does not imply the resource may be sent to any destination for any purpose.

Example:
- local read permitted;
- external model training/upload not permitted.

Purpose may need to be represented explicitly for sensitive operations.

---

## 21. Retention

For every component storing user/KORPUS material, define:

```text
retention purpose
retention duration
owner
purge mechanism
backup behavior
```

OpenClaw session storage and channel-provider retention are especially relevant.

---

## 22. Replay privacy

Retries and replays can duplicate data exposure.

Even read-only retries may repeatedly transmit protected data to external providers.

Retry policy should therefore consider egress cost/sensitivity, not only server load.

---

## 23. Redaction

Redaction is a transformation requiring verification.

Never assume regex replacement is sufficient for all sensitive classes.

If redaction output is used to justify lower classification, the redaction process itself needs tests.

---

## 24. Minimum necessary tool output

Tool responses should return only fields needed by the agent.

Example:
- `korpus_grounds` intentionally returns whether grounds exist without answer text.

This is a valuable architectural pattern:

```text
ask whether data is needed before retrieving/exposing data
```

---

## 25. Data-flow negative controls

```text
IF01 restricted citation -> public channel -> deny
IF02 authorized read -> unrelated upload tool -> deny flow
IF03 secret in tool input -> logging pipeline -> redacted/blocked
IF04 group message from privileged user -> restricted disclosure -> deny
IF05 paired node below classification ceiling -> deny
IF06 model provider not approved for class -> deny
IF07 session history contains old restricted text -> new unauthorized subject -> no reuse
IF08 external MCP server description requests corpus dump -> deny
IF09 route changes between execution and delivery -> re-evaluate
IF10 derived summary from restricted source -> does not auto-downgrade
```

---

## 26. Metrics

Operational metrics may include:

```text
bytes_egressed_by_destination_class
protected_tool_calls_by_channel
blocked_cross-tool_flows
redaction_failures
route_delivery_denials
node_ceiling_denials
model_egress_denials
```

Metrics must avoid embedding sensitive payloads.

---

## 27. Source of truth

KORPUS remains authoritative for its own information policy.

OpenClaw tool policies, sandbox settings and channel configurations provide valuable defense-in-depth restrictions.

The combined rule is:

```text
EffectiveFlow = OpenClawNarrowing ∩ KORPUSFlowPolicy
```

No external layer can widen the KORPUS set.

---

## 28. Terminal principle

The goal is not merely “authorized tools”. It is **authorized information movement**.

A secure orchestration system must answer for every protected output:

```text
what data?
from which source?
for which subject?
for which purpose?
to which destination?
under which policy?
for how long?
with what audit evidence?
```

If those questions cannot be answered, convenience has outrun governance.
