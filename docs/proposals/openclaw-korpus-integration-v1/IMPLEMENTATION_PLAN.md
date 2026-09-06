# Implementation Plan

## 1. Objective

Implement OpenClaw as an external orchestration layer without weakening any KORPUS authorization, evidence, audit or release invariant.

The plan intentionally separates low-risk read integration from side-effecting integration.

## 2. Phase 0 — baseline and contract freeze

Before implementation:

1. record exact KORPUS base SHA and source digest;
2. verify existing MCP server and tool set;
3. inventory OpenClaw integration assumptions against current official OpenClaw docs/version;
4. freeze the first integration surface;
5. explicitly exclude PR #44 from mutation/merge unless separately authorized.

Deliverables:
- OPENCLAW_INTEGRATION_BASELINE.json — an artifact this plan will PRODUCE; it does
  not exist in the tree yet, and is deliberately not written as a path reference so
  that `check_document_references` is not asked to resolve a file nobody has made;
- current KORPUS MCP tool inventory;
- current OpenClaw protocol/capability snapshot;
- threat-model checksum/reference.

## 3. Phase 1 — OpenClaw as KORPUS evidence client

### Goal

Enable an OpenClaw-managed agent to use existing KORPUS MCP evidence tools.

### Runtime sequence

```text
channel message
 -> OpenClaw Gateway
 -> OpenClaw agent
 -> KORPUS MCP client connection
 -> korpus_grounds / ask / quote / verify
 -> OpenClaw agent response
 -> originating channel
```

### Required implementation

- OpenClaw MCP server definition for KORPUS;
- scoped KORPUS-issued token injection via secret reference/environment, not prompt text;
- KORPUS base URL configuration;
- timeout configuration;
- explicit tool allowlist;
- structured logging/correlation id propagation where possible;
- no write/admin capabilities.

### Default tool allowlist

```text
korpus_grounds
korpus_ask
korpus_quote
korpus_verify
```

### Required tests

- tool discovery succeeds;
- empty/invalid token fails closed;
- unauthorized subject remains unauthorized;
- unknown tool cannot execute;
- KORPUS unavailable produces explicit failure, not agent fabrication;
- KORPUS evidence remains byte/hash bound;
- agent draft verification rejects unsupported sentence.

## 4. Phase 2 — channel identity and delivery policy

### Goal

Safely map interaction surfaces to KORPUS subjects and output policies.

### Required work

Define an identity-binding table:

```text
OpenClaw route/account/sender
        -> explicit binding mechanism
        -> KORPUS subject/account
```

Do not infer KORPUS role or clearance from:
- Telegram username;
- WhatsApp number alone;
- OpenClaw agent id;
- Gateway token;
- channel account name.

### Output policy

For each channel class define:
- private/direct only vs group permitted;
- maximum material class;
- whether citations may be returned;
- whether restricted metadata is suppressed;
- whether re-authentication is required for sensitive workflows.

### Negative tests

- same OpenClaw account, different sender -> no identity reuse without explicit binding;
- group chat -> restricted response suppressed/denied according to policy;
- route changed after request -> no delivery to wrong route.

## 5. Phase 3 — typed OpenClaw control adapter

### Goal

Introduce typed read-only OpenClaw control capabilities without generic shell access.

Potential read-only capabilities:
- OpenClaw Gateway health/status;
- channel status;
- session status;
- node status/capability discovery;
- selected conversation metadata.

Implementation shape:

```text
KORPUS/OpenClaw adapter
 -> local capability registry
 -> OpenClaw Gateway protocol/client
 -> response normalization
 -> KORPUS audit/evidence envelope
```

No remote OpenClaw metadata directly defines local authority.

## 6. Phase 4 — side-effect foundation

### Goal

Enable exactly one bounded side effect as a reference implementation.

Recommended first side effect:

```text
reply to originating OpenClaw route
```

Why this is preferable:
- resource is naturally bound to the request route;
- effect is narrow;
- expected post-condition is observable;
- it avoids arbitrary destination selection.

### Required components

- capability registry entry;
- input/output schema;
- resource binding;
- authorization action;
- idempotency key;
- effect ledger;
- adapter timeout/retry behavior;
- outcome-unknown handling;
- audit record;
- negative controls.

### Required property

```text
A caller cannot change the destination to a route that was not authorized/bound.
```

## 7. Phase 5 — node/device capabilities

### Goal

Use OpenClaw paired nodes for device workflows while preserving KORPUS data boundaries.

Start with read-only status/capability discovery.

Any action capability must specify:
- node identity;
- logical device resource;
- required KORPUS permission;
- material egress ceiling;
- effect class;
- post-condition/evidence;
- user/Owner confirmation class where applicable.

Production host shell access remains denied by default.

## 8. Phase 6 — automation/scheduling

### Goal

Permit OpenClaw-triggered recurring or event-driven KORPUS workflows.

Each automation definition is itself state and must be auditable.

Required fields:
- automation id;
- owner/subject;
- trigger/cadence;
- permitted capabilities;
- maximum effect class;
- expiration/disable semantics;
- notification destination binding;
- failure policy.

An automation cannot expand its own capability allowlist.

## 9. Phase 7 — Capability Gateway convergence

If PR #44 or its semantic replacement is later merged and verified, migrate side-effecting OpenClaw calls behind the canonical Capability Gateway.

Target relation:

```text
OpenClaw
 -> KORPUS OpenClaw adapter
 -> Capability Gateway
 -> canonical identity/policy/effect/evidence/audit
```

Do not duplicate gateway logic in an OpenClaw-specific subsystem.

Migration criteria:
- existing OpenClaw capability semantics map exactly to canonical gateway contracts;
- no loss of audit/effect history;
- migration negative controls prove old bypass path is unreachable;
- exact release evidence is regenerated.

## 10. Repository structure proposal

Until generalized gateway integration exists, keep OpenClaw-specific integration narrow.

Potential structure:

```text
apps/api/src/korpus/integrations/openclaw/
  __init__.py
  client.py
  contracts.py
  identity_binding.py
  policy.py
  result.py

apps/api/tests/
  test_openclaw_identity_binding.py
  test_openclaw_read_capabilities.py
  test_openclaw_route_binding.py
  test_openclaw_effect_idempotency.py
  test_openclaw_outcome_unknown.py

config/integrations/
  openclaw-v1.json

scripts/
  verify_openclaw_integration.py
```

If current repository architecture has a more canonical integration path at implementation time, use that instead. Do not create a parallel framework for naming consistency alone.

## 11. Configuration principles

Configuration must contain identifiers and policy, not secrets.

Example conceptual config:

```json
{
  "schema": "korpus.openclaw-integration.v1",
  "enabled": false,
  "gateway": {
    "url_ref": "OPENCLAW_GATEWAY_URL",
    "credential_ref": "OPENCLAW_GATEWAY_TOKEN"
  },
  "capabilities": [
    "korpus_grounds",
    "korpus_ask",
    "korpus_quote",
    "korpus_verify"
  ],
  "max_material_class": "AUTHORIZED_EVIDENCE",
  "writes_enabled": false
}
```

Secrets are injected at runtime through the deployment secret mechanism.

## 12. Observability

Measure at the KORPUS/OpenClaw boundary:
- calls by capability/version;
- authorization denies;
- schema rejects;
- transport failures;
- timeout counts;
- effect state transitions;
- outcome-unknown count;
- egress denials;
- audit commit failures;
- per-capability latency percentiles.

Do not log protected request/response bodies by default.

## 13. CI integration

Add deterministic checks for:
- config schema validity;
- capability registry consistency;
- OpenClaw provider schema digest where pinned/observed;
- no unknown write capability enabled;
- secret absence from tracked files;
- negative controls;
- integration tests with a fake OpenClaw Gateway/provider;
- optional live probe only as separately classified evidence.

A live external service test must not make offline/unit CI nondeterministic unless explicitly placed in an integration lane.

## 14. Deployment sequence

Recommended deployment:

### D0 — disabled
Code/config present, `enabled=false`.

### D1 — local read-only
Loopback/private KORPUS + local OpenClaw Gateway; only evidence tools.

### D2 — private remote Gateway
Authenticated private network/tunnel; still read-only.

### D3 — selected production channel
One direct-message channel/account with explicit KORPUS identity binding.

### D4 — bounded write pilot
One narrow write capability with effect ledger and reconciliation.

### D5 — nodes/automation
Only after previous stages show no authorization/effect boundary failures.

## 15. Rollback

Every phase must have a zero-data-loss rollback:
- disable OpenClaw integration flag;
- revoke OpenClaw/KORPUS scoped token;
- remove provider mapping;
- retain KORPUS audit/effect records;
- native KORPUS API/web remains operational.

Rollback must not require deleting audit evidence.

## 16. Definition of done for v1 foundation

The foundation is implementation-ready when:
- architecture and threat model accepted;
- exact first capability set frozen;
- identity-binding mechanism selected;
- OpenClaw transport/client choice verified against current official protocol;
- negative controls executable;
- no write/admin authority exists in initial configuration;
- rollback is demonstrated;
- integration can be disabled without changing KORPUS core behavior.

## 17. Execution principle

Implement the smallest end-to-end slice that proves the boundary:

```text
one channel/session
 -> one authenticated KORPUS subject
 -> evidence-only MCP tools
 -> one verified factual response
 -> canonical KORPUS audit/evidence semantics unchanged
```

Only after that slice is falsified and verified should authority expand.
