# Implementation Contracts and Interfaces

**Status:** PROPOSED NORMATIVE CONTRACTS FOR IMPLEMENTATION PHASE A/B

This document turns the theory into concrete interface shapes. It intentionally avoids pretending that documentation is runtime code; each contract below must become schema/code/tests before merge-readiness.

---

## 1. Integration boundary

Phase A canonical path:

```text
OpenClaw inbound channel/session
  -> OpenClaw agent/runtime
  -> KORPUS MCP client binding
  -> KORPUS MCP server
  -> KORPUS HTTP API
  -> KORPUS identity/policy/retrieval/evidence/audit
```

No direct database, filesystem, object-store or policy bypass is allowed.

---

## 2. KORPUS MCP tools already available

Current KORPUS main exposes evidence-oriented tools:

```text
korpus_grounds
korpus_ask
korpus_quote
korpus_verify
```

Phase A MUST use these existing semantics rather than creating a second answer path.

---

## 3. OpenClaw integration identity

Define a stable integration identity separate from end-user identity.

```json
{
  "integration_id": "openclaw-korpus-v1",
  "integration_version": "1",
  "korpus_release": "<runtime-derived>",
  "openclaw_release": "<pinned>",
  "gateway_protocol_version": "<measured>",
  "mcp_transport": "stdio|streamable-http|node-hosted",
  "environment": "development|pilot|production"
}
```

This identifies the software bridge, not the KORPUS user.

---

## 4. Route envelope

Every inbound workflow should normalize its route into a local non-authoritative envelope:

```json
{
  "gateway_instance_id": "...",
  "agent_id": "...",
  "channel": "telegram",
  "channel_account_id": "...",
  "peer_kind": "direct",
  "peer_id": "...",
  "thread_id": null,
  "openclaw_session_id": "...",
  "node_id": null
}
```

Properties:
- useful for routing/audit correlation;
- never accepted as direct corpus permission;
- exact return route can be compared before delivery.

---

## 5. KORPUS subject binding

A separate binding maps route context to KORPUS principal where deployment policy permits.

```json
{
  "binding_id": "...",
  "route_selector_digest": "<sha256>",
  "korpus_subject_id": "...",
  "binding_version": 1,
  "valid_from": "...",
  "valid_until": null,
  "revoked_at": null,
  "assurance_class": "explicit_operator_binding"
}
```

The binding itself must not duplicate role/clearance/corpus authority; those remain current KORPUS state.

---

## 6. No implicit user mapping

Forbidden mappings:

```text
Telegram username == KORPUS username
phone number string == KORPUS account
OpenClaw agent id == KORPUS principal
node id == KORPUS principal
```

unless an explicit binding procedure creates and verifies the relation.

---

## 7. Phase A tool policy

OpenClaw-side allowlist SHOULD expose only:

```text
korpus_grounds
korpus_ask
korpus_quote
korpus_verify
```

KORPUS-side policy independently enforces actual authorization.

Defense-in-depth theorem:

```text
Executable = OpenClawAllows(tool) ∧ KORPUSAllows(subject, action, resource)
```

OpenClaw may narrow; it cannot widen.

---

## 8. Ground-first workflow contract

Recommended response workflow:

```text
1. receive user question
2. resolve/bind KORPUS subject
3. call korpus_grounds(question, as_of?)
4. if no grounds -> answer with explicit abstention/no-ground state
5. if grounds -> call korpus_ask
6. compose response using returned text/citations
7. call korpus_verify on composed critical prose
8. if verify fails -> remove/rewrite unsupported sentence or abstain
9. authorize delivery to original route
10. send response
```

This makes evidence verification part of the normal path rather than an optional postscript.

---

## 9. Ground response envelope

Normalized internal shape:

```json
{
  "has_grounds": true,
  "status": "answered",
  "decision_reason": "...",
  "citation_count": 3,
  "sources": ["..."],
  "admission": {},
  "corpus_release": "..."
}
```

Do not derive extra authorization from `has_grounds`.

It only answers whether KORPUS has admissible answer grounds for the already authorized request path.

---

## 10. Ask response envelope

The OpenClaw integration should preserve KORPUS-provided fields rather than flattening them into one string.

At minimum:

```json
{
  "status": "answered|abstained|...",
  "decision_reason": "...",
  "text": "...",
  "citations": [],
  "citation_count": 0,
  "corpus_release": "...",
  "admission": {},
  "limitations": [],
  "calibration_id": "..."
}
```

If the agent discards evidence metadata, it destroys the ability to verify its own composition.

---

## 11. Citation envelope

Preserve:

```text
quote
title
source_uri
page
section
span_id
quote_hash
span_hash
source_hash
starts_mid_sentence
adjudication_reason
```

A rendered answer may simplify presentation, but the workflow state should retain exact citation identity for verification/audit.

---

## 12. Draft-verification contract

Before sending critical composed prose:

```json
{
  "draft": "agent-composed answer",
  "quotes": ["exact quote 1", "exact quote 2"]
}
```

Expected result shape:

```json
{
  "supported": true,
  "sentences": [
    {
      "sentence": "...",
      "supported": true,
      "reason": "...",
      "carried_by": "..."
    }
  ],
  "unsupported_count": 0
}
```

Policy:

```text
critical response may claim KORPUS-grounded support
only if unsupported_count == 0
```

or unsupported material is visibly separated as non-KORPUS inference under an explicitly allowed product mode.

---

## 13. As-of semantics

If user asks for historical/current-at-date state, route `as_of` exactly.

Do not let model paraphrase vague relative dates into an arbitrary timestamp without explicit resolution.

Recommended normalized field:

```text
as_of = ISO date/time or null
resolution_source = explicit_user | deterministic_parser | clarified
```

---

## 14. Error taxonomy crossing the boundary

Do not flatten all tool errors into “KORPUS failed”.

Normalize:

```text
AUTHENTICATION_REQUIRED
AUTHORIZATION_DENIED
NO_GROUNDS
VALIDATION_FAILED
KORPUS_UNAVAILABLE
MCP_TRANSPORT_FAILED
TIMEOUT
SCHEMA_MISMATCH
VERIFY_UNSUPPORTED
ROUTE_STALE
DELIVERY_FAILED
```

Each class gets distinct recovery semantics.

---

## 15. No-ground semantics

No-ground response is not an infrastructure error.

```text
NO_GROUNDS = valid epistemic outcome
```

The agent should not replace it with:
- model memory;
- web search;
- session transcript;
- guess.

unless the user explicitly requested a mode outside KORPUS-grounded answer semantics and product policy allows it.

---

## 16. Transport failure semantics

MCP/network failure is different:

```text
KORPUS_UNAVAILABLE != KORPUS_HAS_NO_GROUNDS
```

User-facing behavior should preserve the distinction.

---

## 17. OpenClaw configuration principle

Implementation should pin an exact tested OpenClaw release and tool configuration.

Conceptual configuration:

```text
agent/workspace: dedicated KORPUS integration context
MCP server: KORPUS MCP endpoint/process
allowed tools: exact evidence tool set
sandbox/plugin policy: minimum required exposure
channel bindings: explicit
node tools: disabled for Phase A unless separately required
```

Do not copy illustrative config into production until checked against the implementation-time OpenClaw schema.

---

## 18. MCP server deployment modes

Possible Phase A modes:

### A. Local stdio

```text
OpenClaw host -> child process scripts/run_mcp_server.py -> local KORPUS API
```

Advantages:
- narrow local boundary;
- simple token handling;
- fewer network surfaces.

Risks:
- process lifecycle;
- environment leakage;
- local host trust assumptions.

### B. Streamable HTTP / remote MCP bridge if supported by chosen deployment

Advantages:
- independent lifecycle;
- remote gateway topology.

Risks:
- TLS/auth/network policy;
- more exposed surface.

### C. Node-hosted MCP

OpenClaw documentation supports node-hosted MCP servers in current node architecture.

Use only if the KORPUS deployment model actually requires the integration process on a paired node.

Node-hosting does not grant KORPUS data authority.

---

## 19. Token handling

KORPUS MCP currently requires its own token.

Rules:
- token never embedded in prompt;
- token never returned to model/tool output;
- token not stored in channel transcript;
- token scope minimized;
- revocation documented;
- secrets passed via supported secret/env mechanism;
- logs redact authorization headers.

OpenClaw/Gateway credential and KORPUS credential remain separate identities.

---

## 20. Context minimization

Only send to the model what it needs.

Do not place full:
- KORPUS auth object;
- policy registry;
- secret-bearing config;
- entire corpus;
- audit chain;

into the model context.

Expose typed results, selected evidence, and minimal operational state.

---

## 21. Prompt boundary

System/developer instructions should state invariant behavior, but deterministic controls enforce it.

Remote content must be delimited as data.

Examples of untrusted data:
- KORPUS source text;
- OpenClaw tool descriptions from external MCP servers;
- user messages;
- web content;
- node OCR/screen text.

No untrusted text is promoted into privileged instruction solely because an agent framework labels it “tool metadata”.

---

## 22. Route-binding cache

If route->KORPUS subject binding is cached, cache only the mapping identity/version, not current authority.

For critical action:

```text
route mapping may be cached
KORPUS roles/permissions must be current enough for policy semantics
```

Revocation must invalidate or override cache.

---

## 23. Conversation/session mapping

OpenClaw conversation session and KORPUS conversation are separate objects.

Possible mapping:

```json
{
  "openclaw_session_id": "...",
  "korpus_conversation_id": "...",
  "binding_version": 1,
  "subject_id": "..."
}
```

Never infer evidence from OpenClaw transcript.

KORPUS conversation history remains context under KORPUS semantics, not source authority.

---

## 24. Correlation identifiers

Carry where possible:

```text
workflow_id
openclaw_session_id
korpus_request_id
korpus_policy_decision_id
mcp_call_id
provider/node request id where applicable
```

Correlation aids debugging without changing authority.

---

## 25. Phase B read-only operational contract

Candidate tools may include typed reads such as:

```text
korpus_release_status
korpus_runtime_identity
korpus_allowed_corpus_metadata
korpus_audit_verification_status
```

Every new tool must declare:
- exact data class;
- required permission;
- resource scope;
- maximum response size;
- evidence/audit semantics;
- negative controls.

No generic `read_file(path)` against production host.

---

## 26. Side-effect capability schema

Before Phase C, every side-effect capability should compile to something like:

```json
{
  "capability_id": "external.message.send",
  "version": "1",
  "effect_class": "TRANSACTIONAL_SIDE_EFFECT",
  "action": "message:send",
  "resource_schema": "...",
  "input_schema_sha256": "...",
  "output_schema_sha256": "...",
  "idempotency": "required",
  "reconciliation": "required_on_unknown",
  "egress_policy": "...",
  "audit_policy": "critical",
  "max_attempts": 2
}
```

This is a local KORPUS contract, not provider metadata.

---

## 27. Effect invocation envelope

```json
{
  "invocation_id": "...",
  "idempotency_key": "...",
  "subject_id": "...",
  "capability_id": "...",
  "capability_version": "...",
  "logical_resource": "...",
  "canonical_input_digest": "...",
  "route_binding_digest": "...",
  "release": "..."
}
```

No adapter should accept a looser equivalent for critical writes without explicit normalization rules.

---

## 28. Result envelope

For future governed capabilities:

```json
{
  "invocation_id": "...",
  "status": "COMMITTED|FAILED_KNOWN_NO_EFFECT|OUTCOME_UNKNOWN",
  "output": {},
  "output_digest": "...",
  "evidence": [],
  "effect_receipt": {},
  "audit_reference": "..."
}
```

No generic Boolean `success` for effectful actions.

---

## 29. Delivery envelope

Before channel response:

```json
{
  "origin_route_digest": "...",
  "current_route_digest": "...",
  "classification": "...",
  "delivery_allowed": true,
  "payload_digest": "..."
}
```

This becomes important once multiple channels/accounts/nodes are active.

---

## 30. Build-time/generated contract discipline

Where schemas can be generated from one canonical source, generate them.

Avoid:
- OpenClaw-side manually copied KORPUS enum sets;
- duplicated permission lists;
- hand-maintained release ids;
- second API route registry.

Use source-generated contracts and drift checks.

---

## 31. Contract versioning rule

A version must change when semantics change materially.

Material examples:
- effect class changes;
- required permission changes;
- response data sensitivity widens;
- input resource interpretation changes;
- retry/idempotency behavior changes.

Adding optional presentation metadata may be backward compatible but still requires schema digest change.

---

## 32. Acceptance gates for Phase A contract

```text
A1 exact tested OpenClaw version recorded
A2 KORPUS MCP server starts fail-closed without token
A3 only intended tools visible to Phase A agent
A4 valid ground/ask/quote/verify workflow works
A5 unauthorized KORPUS resource remains denied
A6 NO_GROUNDS distinct from transport failure
A7 tool prompt injection cannot alter KORPUS policy
A8 session transcript not used as KORPUS evidence
A9 unsupported composed sentence blocked by verify
A10 route delivery does not cross peer/session
A11 logs contain no KORPUS token
A12 exact KORPUS/OpenClaw versions captured in evidence
```

---

## 33. Acceptance gates for Phase C contract

Additional:

```text
C1 exact capability/resource binding
C2 durable idempotency reservation
C3 duplicate replay -> one logical effect
C4 ambiguous timeout -> OUTCOME_UNKNOWN
C5 reconciliation resolves known cases
C6 no blind retry from OUTCOME_UNKNOWN
C7 audit committed before critical success return
C8 wrong-resource substitution fails
C9 policy deny cannot be overridden by agent/provider metadata
C10 compensation independently authorized
```

---

## 34. Terminal principle

A good integration contract makes the safe path easier than ad-hoc integration.

The desired developer experience is:

```text
explicit identity
+ typed capability
+ exact resource
+ generated schema
+ deterministic policy
+ bounded effect
+ structured evidence
+ canonical audit
```

not:

```text
prompt says “be careful”
+ generic tool
+ broad token
+ stringly typed payload
+ hope
```
