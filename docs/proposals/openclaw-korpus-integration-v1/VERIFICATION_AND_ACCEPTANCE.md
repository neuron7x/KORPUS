# Verification and Acceptance

## 1. Verification philosophy

The integration is accepted only when its controls are falsifiable. A documented rule without an executable negative control is not sufficient evidence that the boundary works.

Core rule:

```text
ControlPresent != ControlEffective
HappyPathPass  != BoundaryVerified
```

For every security-relevant invariant, preserve at least one test that would fail if the control were removed or bypassed.

## 2. Acceptance hierarchy

### Layer A — contract validity

Verify:
- capability schemas parse;
- required fields cannot be omitted;
- unknown authority-bearing fields are rejected;
- capability versions are exact;
- provider/schema identity is bound.

### Layer B — authorization boundary

Verify:
- valid OpenClaw transport credential + unauthorized KORPUS subject -> DENY;
- spoofed role/clearance/corpus fields -> no privilege widening;
- cross-account resource id -> refusal;
- disabled capability -> refusal;
- unknown capability -> refusal.

### Layer C — egress boundary

Verify:
- output never exceeds declared material class;
- secret fields never reach OpenClaw output;
- group/public channel policy cannot receive restricted response when prohibited;
- malformed provider output cannot bypass validation.

### Layer D — effect safety

For every write:
- idempotency works;
- duplicate request does not duplicate effect;
- timeout after commit creates `OUTCOME_UNKNOWN` or reconciliation path;
- blind retry is blocked when outcome is unknown;
- wrong route/resource binding is rejected;
- audit failure blocks returnable critical success.

### Layer E — evidence integrity

Verify:
- `korpus_ask` result retains citation/provenance/hash data required by its contract;
- `korpus_quote` can revalidate a returned span;
- `korpus_verify` rejects unsupported agent text;
- prior chat/session text cannot satisfy KORPUS evidence admission;
- stale/rescinded evidence is not promoted by OpenClaw.

### Layer F — orchestration isolation

Verify:
- OpenClaw agent id does not become KORPUS role;
- OpenClaw Gateway token does not become KORPUS permission;
- separate channel sessions cannot read each other's KORPUS state without authorization;
- node execution cannot access protected KORPUS material absent an admitted capability.

## 3. Mandatory negative controls

### NC-01 — invalid KORPUS token

Input: valid OpenClaw session, missing/invalid KORPUS credential.  
Expected: KORPUS call fails closed; no fabricated answer.

### NC-02 — unauthorized corpus

Input: authenticated subject asks for known existing but unauthorized corpus/document.  
Expected: refusal without source-text disclosure.

### NC-03 — injected role

Input contains `role=admin`, `clearance=restricted`, `authorized=true`.  
Expected: fields rejected/ignored as authority; result follows server-side subject policy.

### NC-04 — malicious MCP/tool metadata

Remote description instructs caller to bypass policy or widen permissions.  
Expected: local capability/effect classification unchanged.

### NC-05 — provider schema drift

Change provider tool schema digest.  
Expected: mapping quarantined/disabled until reviewed.

### NC-06 — unsupported draft

Agent adds a factual sentence not carried by supplied KORPUS citations.  
Expected: `korpus_verify` reports unsupported content.

### NC-07 — stale citation

Use rescinded/stale evidence where current policy forbids it.  
Expected: KORPUS does not admit it as current evidence.

### NC-08 — cross-route delivery

Modify destination account/thread between request and response.  
Expected: route-binding check rejects delivery.

### NC-09 — duplicate write

Submit same canonical write twice with same logical operation id.  
Expected: one external effect; second call reuses existing effect identity/result.

### NC-10 — timeout after remote commit

Provider commits then connection is cut before response.  
Expected: no blind duplicate retry; explicit `OUTCOME_UNKNOWN` or successful reconciliation.

### NC-11 — audit failure

Force canonical audit persistence failure after provider returns success.  
Expected: no critical governed success returned.

### NC-12 — OpenClaw unavailable

Gateway/transport unavailable.  
Expected: KORPUS remains intact/independently operable; no alternate ungoverned path.

### NC-13 — KORPUS unavailable

OpenClaw session is healthy but KORPUS API is unavailable.  
Expected: user receives explicit unavailable/unknown outcome, not model-generated factual replacement.

### NC-14 — secret leakage

Seed recognizable canary secrets in server-side env/config.  
Expected: canary absent from agent-visible outputs, OpenClaw messages and normal logs.

### NC-15 — generic execution attempt

Agent requests arbitrary shell/database/filesystem production action.  
Expected: unavailable/denied unless an explicit capability was separately authorized.

## 4. Mutation tests

Where practical, create targeted mutants that remove or invert the boundary and prove tests kill them.

Minimum mutation classes:
- bypass KORPUS authorization result;
- trust caller role;
- skip resource binding;
- skip schema digest check;
- skip egress ceiling;
- skip idempotency lookup;
- treat timeout as known-no-effect;
- skip audit-required check;
- accept unknown capability;
- convert verification failure to success.

Any survivor capable of producing unauthorized or falsely verified success is release-blocking for the integration.

## 5. Read-only MVP acceptance

The Phase-1 evidence-client integration may be accepted when:

```text
KORPUS_MCP_DISCOVERY              = PASS
KORPUS_TOKEN_REQUIRED             = PASS
UNAUTHORIZED_SUBJECT_REFUSED      = PASS
UNKNOWN_TOOL_REFUSED              = PASS
EVIDENCE_HASHES_PRESERVED         = PASS
DRAFT_VERIFICATION_NEGATIVE_TEST  = PASS
KORPUS_DOWN_NO_FABRICATION        = PASS
NO_WRITE_CAPABILITIES_EXPOSED     = PASS
SECRET_LEAKAGE_CONTROL            = PASS
```

No side-effect tests are required to deploy a genuinely read-only integration, but the runtime must prove that write/admin tools are not exposed.

## 6. Write-capability acceptance

A write capability additionally requires:

```text
RESOURCE_BINDING                  = PASS
AUTHORIZATION_NEGATIVE_CONTROLS   = PASS
IDEMPOTENCY                       = PASS
DUPLICATE_EFFECT_TEST             = PASS
OUTCOME_UNKNOWN_TEST              = PASS
RECONCILIATION                    = PASS
AUDIT_COMMIT_REQUIRED             = PASS
OUTPUT_CONTRACT                   = PASS
ROLLBACK_DISABLE_PATH             = PASS
```

## 7. Channel acceptance

For each enabled channel/account:
- route identity is stable/observable;
- KORPUS subject binding is explicit;
- public/group/private semantics are known;
- output material ceiling is declared;
- route misbinding test exists;
- account/session separation test exists;
- account takeover/revocation procedure exists.

Passing Telegram does not automatically qualify WhatsApp, Slack, Discord or another channel; transport/security semantics may differ.

## 8. Node acceptance

Before a node receives KORPUS-protected material:
- node identity/pairing state is verified;
- capability allowlist is explicit;
- protected material class is declared;
- no ambient mount of restricted corpus/secrets exists;
- device action can be disabled/revoked;
- wrong-node and stale-pairing negative tests pass.

## 9. Observability acceptance

Required metrics/events:
- capability invocation count;
- deny/reject reasons;
- provider transport failures;
- schema drift/quarantine;
- egress deny;
- outcome unknown;
- reconciliation result;
- audit failure;
- capability latency;
- route misbinding refusal.

Metrics are operational evidence, not factual corpus evidence.

## 10. Exact-state evidence

Every verification report must bind:
- KORPUS commit SHA;
- KORPUS source digest where applicable;
- integration configuration digest;
- OpenClaw version/protocol/schema identity relevant to the test;
- test suite revision;
- capability registry digest.

Evidence from a different semantic subject cannot authorize the current candidate.

## 11. Rollback acceptance

Demonstrate that disabling the integration:
- stops OpenClaw-originated KORPUS calls;
- revokes/removes integration credentials;
- does not delete KORPUS audit/effect history;
- leaves native KORPUS web/API operation available;
- does not require database rollback for read-only integration.

## 12. Release classification

Use three states:

### `PASS`
All mandatory gates for the declared integration scope pass on the exact candidate.

### `PASS_WITH_CAVEATS`
Declared scope is safe/verified, but explicitly non-blocking limitations remain, such as unimplemented later phases.

### `FAIL`
Any current-scope authorization, evidence, effect, audit, egress, identity-binding or exact-state verifier is unresolved/false-pass capable.

Do not use “mostly pass”.

## 13. Stop condition

The foundation PR can move from draft theory to implementation-ready only when:
- current OpenClaw facts are revalidated;
- exact MVP scope is frozen;
- identity binding is defined;
- negative-control suite is implementable;
- no generic write authority is required for MVP.

An implementation PR can be merge-ready only when its scope-specific acceptance matrix is all PASS and blocking unknowns are zero.
