# Formal Requirements

## 1. Requirement semantics

Keywords `MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, and `MAY` are normative within this proposal.

A requirement is satisfied only by evidence that can be bound to the exact implementation state. Documentation alone does not satisfy executable requirements.

## 2. Authority requirements

### AUTH-001
OpenClaw MUST NOT be a KORPUS authorization authority.

### AUTH-002
Every protected KORPUS invocation originating through OpenClaw MUST be authorized by canonical KORPUS identity/policy state.

### AUTH-003
OpenClaw-supplied role, clearance, tenant, corpus, compartment, `trusted`, or `authorized` fields MUST NOT widen KORPUS access.

### AUTH-004
A valid OpenClaw Gateway/MCP/channel credential MUST NOT be sufficient evidence of KORPUS action authorization.

### AUTH-005
Unknown or unresolved authorization state MUST fail closed.

## 3. Capability requirements

### CAP-001
Every executable KORPUS-facing operation MUST map to an exact local capability id and version.

### CAP-002
Unknown capabilities MUST fail closed.

### CAP-003
Remote OpenClaw/MCP metadata MUST NOT create or widen local capability authority automatically.

### CAP-004
Capability input and output MUST be validated against local contracts.

### CAP-005
Provider schema/semantic drift that can widen authority or change effects MUST quarantine/disable the mapping until reconciled.

### CAP-006
Generic production shell, database, filesystem and release-signing authority MUST NOT be exposed in the initial integration.

## 4. Identity requirements

### ID-001
OpenClaw agent id, session key, route, sender and channel account MUST remain distinct from KORPUS subject identity.

### ID-002
Channel-to-KORPUS identity binding MUST be explicit, revocable and auditable.

### ID-003
Cross-account or cross-session identifiers supplied by a caller MUST NOT override server-side account/resource scope.

## 5. Evidence requirements

### EVD-001
Factual KORPUS outputs used by an OpenClaw agent MUST retain the evidence/provenance fields required by the KORPUS tool contract.

### EVD-002
OpenClaw transcript/session history MUST NOT be promoted to KORPUS evidence.

### EVD-003
Agent/model output MUST NOT become a factual source merely because `korpus_verify` accepted supported sentences.

### EVD-004
Stale, rescinded, unauthorized or policy-blocked evidence MUST remain inadmissible through OpenClaw.

### EVD-005
When KORPUS lacks admissible evidence, OpenClaw MUST surface refusal/unknown rather than fabricate a replacement factual answer.

## 6. Egress requirements

### EGR-001
Every capability MUST declare a maximum output/material class.

### EGR-002
Secrets and credentials MUST NEVER be emitted in normal OpenClaw tool outputs.

### EGR-003
Channel-specific delivery policy MUST be able to further restrict material returned to group/public contexts.

### EGR-004
A lower-trust OpenClaw destination MUST NOT widen the data KORPUS would otherwise disclose.

## 7. Side-effect requirements

### EFF-001
Write capabilities MUST bind a logical resource before dispatch.

### EFF-002
Write capabilities MUST have explicit idempotency semantics.

### EFF-003
Timeout/transport failure MUST NOT be interpreted as proof that no effect occurred.

### EFF-004
Ambiguous side-effect outcomes MUST enter an explicit `OUTCOME_UNKNOWN`/reconciliation state.

### EFF-005
Blind retry MUST be prohibited when duplicate effect is possible and outcome is unknown.

### EFF-006
Critical success MUST NOT be returned if required canonical KORPUS audit persistence fails.

### EFF-007
Compensation MUST NOT be described as rollback/atomicity unless those properties are actually proven.

## 8. OpenClaw routing requirements

### ROUTE-001
Responses intended for the originating channel MUST be bound to the exact authorized route/account/thread resource.

### ROUTE-002
Caller-modified destination identifiers MUST NOT silently redirect protected output.

### ROUTE-003
Multi-agent routing MUST NOT be treated as KORPUS authorization separation by itself.

## 9. Node/device requirements

### NODE-001
A paired OpenClaw node MUST NOT receive unrestricted KORPUS corpus or secrets by default.

### NODE-002
Each device-side operation involving KORPUS data MUST have an explicit capability/effect policy.

### NODE-003
Node identity/pairing MUST be observable and revocable.

## 10. Audit requirements

### AUD-001
KORPUS audit remains canonical for KORPUS operations.

### AUD-002
OpenClaw session/channel/node identifiers MAY be recorded as correlation context but MUST NOT replace KORPUS subject/policy/evidence fields.

### AUD-003
Critical invocation records SHOULD include capability/version, resource, input digest, policy-decision reference, execution state, evidence/output digest and release/runtime identity.

## 11. Availability requirements

### AVL-001
OpenClaw failure MUST NOT corrupt KORPUS state.

### AVL-002
KORPUS failure MUST result in explicit unavailable/unknown behavior, not ungrounded agent fallback for KORPUS-authoritative facts.

### AVL-003
No hidden direct-database/filesystem fallback MUST bypass the KORPUS integration boundary.

## 12. Operational requirements

### OPS-001
The integration MUST be independently disableable/revocable without deleting KORPUS audit history.

### OPS-002
Integration credentials MUST be stored outside tracked source and agent prompts/workspaces.

### OPS-003
OpenClaw version/protocol assumptions MUST be revalidated before implementation/release.

### OPS-004
Operational telemetry MUST avoid logging protected bodies by default.

## 13. Verification requirements

### VER-001
Every authority/effect/evidence invariant MUST have at least one falsifying negative control.

### VER-002
A verifier capable of false-PASS on a mandatory integration invariant blocks merge.

### VER-003
Verification evidence MUST bind the exact KORPUS candidate and relevant OpenClaw protocol/config subject.

### VER-004
A test from another semantic subject MUST NOT authorize the current integration candidate without explicit equivalence proof.

### VER-005
Read-only MVP acceptance MUST prove absence of exposed write/admin capabilities.

## 14. Release requirements

### REL-001
This proposal MUST NOT alter KORPUS production authority by documentation alone.

### REL-002
Initial implementation SHOULD be read/evidence-only.

### REL-003
Side effects MAY be enabled only after effect ledger, idempotency, reconciliation and audit tests pass.

### REL-004
PR #44 MUST remain independently governed; this proposal MUST NOT merge or mutate it implicitly.

### REL-005
Owner/release authority MUST remain separate from technical orchestration.

## 15. Traceability rule

Implementation PRs derived from this proposal SHOULD identify affected requirement ids in code/test commits and acceptance reports. Any requirement intentionally deferred must be explicitly marked `OUT_OF_SCOPE` for the declared integration phase, with a reason proving that it cannot alter that phase's decision.
