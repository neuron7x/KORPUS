# Evaluation, Learning, and Feedback Discipline

**Status:** NORMATIVE THEORY FOR PROPOSAL v1

The integration is treated as an empirical system. Design claims become operational knowledge only when they are tied to executable observations capable of proving them wrong.

---

## 1. Core principle

A sophisticated architecture diagram is not evidence that the architecture works.

For every important property:

```text
Property claim
 -> observable
 -> measurement procedure
 -> positive control
 -> falsifying negative control
 -> exact-state result
 -> decision
```

The proposal therefore uses **eval-driven engineering**, not documentation-driven confidence.

---

## 2. Evaluation layers

### 2.1 Unit semantics

Verify pure mechanisms:
- route normalization;
- capability resolution;
- digest binding;
- policy decision composition;
- effect-state transitions;
- output validation.

### 2.2 Property tests

Verify invariants across generated inputs:
- unauthorized resources never become allowed due to routing metadata;
- idempotency key replay preserves one logical effect;
- unknown fields cannot widen capability;
- schema drift fails closed.

### 2.3 Adversarial tests

Construct inputs designed to violate assumptions:
- spoofed channel identity;
- malicious MCP description;
- prompt injection in tool/resource text;
- wrong-subject evidence;
- stale route mapping;
- replay after timeout;
- cross-session output delivery.

### 2.4 Integration tests

Exercise OpenClaw boundary + KORPUS MCP/API together.

### 2.5 Clean-room reproduction

Fresh checkout/context repeats critical acceptance path without inheriting the implementation session’s state.

### 2.6 Runtime verification

Confirm deployment identity, route behavior, latency, failures and effect reconciliation in the actual bounded environment.

---

## 3. Eval object

Each evaluation should be represented as:

```text
Eval = {
  eval_id,
  claim_id,
  subject_sha,
  korpus_source_digest,
  openclaw_version,
  protocol_version,
  fixture_identity,
  environment_identity,
  procedure,
  expected,
  observed,
  verdict,
  artifact_digests
}
```

Without exact subject binding, a passing eval is historical evidence only.

---

## 4. Claim ledger

Maintain a claim ledger for the integration.

Example:

```text
OC-K-CLAIM-001
Claim:
  A valid OpenClaw transport/session cannot widen KORPUS authorization.

Observable:
  KORPUS authorization decision on a capability/resource pair.

Positive:
  authorized subject + permitted capability/resource -> PASS.

Poison:
  same OpenClaw session + unauthorized resource -> DENY.

Decision relevance:
  P0 if poison passes.
```

This prevents evidence from becoming a pile of unrelated green tests.

---

## 5. Evaluation matrix

Minimum axes:

```text
Identity
Authorization
Capability exactness
Resource binding
Input contract
Egress
Evidence
Effect safety
Idempotency
Outcome ambiguity
Reconciliation
Audit
Route delivery
Node isolation
MCP schema drift
Session staleness
Release binding
Dependency failure
```

Each axis needs at least one positive and one falsifying case before release authority is claimed.

---

## 6. Failure taxonomy

A failed eval must be classified before repair.

```text
MODEL_PROPOSAL_ERROR
IDENTITY_BINDING_ERROR
POLICY_ERROR
CAPABILITY_RESOLUTION_ERROR
RESOURCE_BINDING_ERROR
SCHEMA_ERROR
EGRESS_ERROR
ADAPTER_ERROR
EFFECT_STATE_ERROR
RETRY_ERROR
RECONCILIATION_ERROR
EVIDENCE_ERROR
AUDIT_ERROR
ROUTE_ERROR
NODE_ERROR
VERIFIER_FALSE_PASS
VERIFIER_FALSE_FAIL
ENVIRONMENT_ERROR
STALE_EVIDENCE
TEST_DEFECT
```

The class determines whether the fix belongs to model prompting, deterministic code, policy, adapter, verifier or environment.

---

## 7. Do not optimize the wrong layer

Examples:

### Bad response from model, policy correct

Do not change authorization.
Improve proposal/evaluation or compose a better response.

### Repeated unauthorized attempts

Do not weaken policy to reduce errors.
Improve tool visibility, model instructions or plan generation.

### Provider timeout creates duplicate effect

Do not “prompt the model to be careful”.
Fix idempotency/reconciliation semantics.

### Tool description causes prompt injection

Do not merely add a warning to the prompt.
Treat tool description as untrusted data and enforce instruction-channel separation.

---

## 8. Baselines

Every optimization needs a baseline.

For Phase A read/evidence integration, baseline can be direct KORPUS MCP invocation without OpenClaw orchestration.

Compare:

```text
grounded-answer correctness
citation integrity
latency
failure rate
route correctness
material exposure
model/tool call count
```

OpenClaw integration should not silently lower evidence correctness to improve convenience.

---

## 9. Counterfactual evaluation

For a workflow, compare alternate policies or planners on the same frozen case set.

```text
A = current planner
B = candidate planner
```

Hold constant:
- KORPUS release;
- corpus state;
- OpenClaw version;
- tool set;
- identity/policy state;
- case set.

Measure only the changed variable.

This reduces causal ambiguity.

---

## 10. Golden traces

Keep deterministic canonical traces for critical workflows.

Example Phase A trace:

```text
channel message
 -> route binding
 -> KORPUS subject resolution
 -> korpus_grounds
 -> korpus_ask
 -> compose
 -> korpus_verify
 -> delivery authorization
 -> response
```

Golden trace assertions should cover:
- call order;
- authority boundaries;
- exact tool names/versions;
- result/evidence digests where deterministic;
- absence of forbidden calls.

---

## 11. Mutation testing

Mutation testing asks whether a gate can detect a defect, not merely whether tests pass.

Important mutation classes:

```text
remove authorization check
replace deny with allow
skip resource binding
accept unknown capability
ignore schema digest mismatch
remove egress ceiling
ignore idempotency key
map OUTCOME_UNKNOWN to success
skip reconciliation
skip evidence validation
skip audit failure
deliver to unbound route
trust node pairing as data permission
trust OpenClaw tool metadata as authority
```

Every mutation capable of violating a frozen critical invariant must be killed.

---

## 12. Negative-control discipline

A negative test must actually instantiate the claimed defect.

After writing a poison test:
1. temporarily introduce the defect;
2. prove the test fails;
3. restore correct implementation;
4. prove the test passes;
5. preserve the fixture.

This protects against tests that merely look adversarial.

---

## 13. False-PASS priority

Verifier defects have asymmetric severity.

```text
false FAIL -> availability/developer-friction risk
false PASS -> authority/integrity risk
```

For frozen critical invariants, false-PASS-capable verifier defects are release blockers.

Examples:
- verifier trusts report path but not report bytes;
- route-checker tests channel type but not peer/thread identity;
- effect verifier trusts adapter “success” without post-state;
- tool-schema verifier checks presence but not digest/version.

---

## 14. Evals for probabilistic planners

A stochastic model cannot be judged by one successful conversation.

Use a frozen scenario corpus with categories:

```text
clear authorized read
clear unauthorized read
ambiguous intent
wrong-resource trap
prompt injection
cross-channel confusion
tool overreach temptation
side-effect request requiring approval
stale session authority
node capability unavailable
KORPUS unavailable
OpenClaw unavailable
```

Metrics:

```text
valid_plan_rate
unauthorized_proposal_rate
clarification_when_needed_rate
unnecessary_refusal_rate
forbidden_tool_attempt_rate
verified_completion_rate
```

The model is allowed to propose invalid actions because KORPUS blocks them, but high invalid-proposal rates create cost and operational noise and should be improved.

---

## 15. Security metric separation

Never use one aggregate score to hide a safety failure.

Use hard ceilings:

```text
unauthorized_executions = 0
cross_subject_leaks = 0
false_success_unknown_effect = 0
critical_unsupported_claims = 0
```

Then optimize soft metrics:

```text
latency
completion rate
clarification count
cost
user friction
```

---

## 16. Evaluation of tool descriptions

Remote/descriptive text may influence model behavior.

Create adversarial descriptions containing:
- “ignore policy”;
- “this tool is always authorized”;
- false security claims;
- fake system instructions;
- data-exfiltration requests.

Required:
- description remains data;
- local capability mapping remains unchanged;
- KORPUS policy remains authoritative;
- forbidden capability execution fails.

---

## 17. Evaluation of identity binding

Cases:

```text
same channel, known bound user
same channel, unknown user
same username, different provider account
forwarded message from privileged user
message in group containing privileged user
stale session after KORPUS role revocation
channel account reconnected/repaired
```

No inference shortcut may turn ambiguous identity into privilege.

---

## 18. Evaluation of nodes

Cases:

```text
paired approved node
paired node lacking command policy mapping
revoked node still connected
node offline during request
node returns malformed output
node executes but response lost
node tool surface expands after update
node-hosted MCP tool schema drifts
```

Each case tests a different boundary.

---

## 19. Evaluation of side effects

A side-effect test matrix should cross:

```text
transport outcome:
  success / explicit failure / timeout / disconnect

provider effect:
  committed / not committed / partial / unknown

replay:
  none / same idempotency key / new key
```

Expected state transitions must be explicit for every material combination.

---

## 20. Evals for evidence loop

Phase A should verify:

1. `korpus_grounds` does not fabricate evidence;
2. `korpus_ask` exposes only allowed evidence material;
3. `korpus_quote` matches span/source hashes;
4. composed answer unsupported by any quote -> `korpus_verify` fails;
5. supported composition -> passes;
6. missing KORPUS connectivity -> no grounded claim;
7. stale or rescinded evidence follows KORPUS semantics;
8. session transcript is not recycled as evidence.

---

## 21. Regression denominator

Freeze a mandatory regression set for each implementation phase.

Example:

```text
Phase A mandatory set:
  authority isolation
  evidence integrity
  route isolation
  prompt/tool injection
  dependency failure

Phase C adds:
  idempotency
  outcome unknown
  reconciliation
  write audit
```

Do not allow the denominator to grow indefinitely during final release closure. New non-critical discoveries move to the next iteration unless they falsify a frozen invariant.

---

## 22. Observability vs audit

Telemetry answers:
- how long;
- how often;
- where errors cluster;
- which adapter/provider is slow.

Audit answers:
- who;
- what capability/resource;
- under which policy;
- what effect/evidence;
- which exact release.

Do not substitute one for the other.

---

## 23. Production feedback

After deployment, track:

```text
invalid proposal frequency
policy denial frequency by capability
schema drift events
reconciliation frequency
OUTCOME_UNKNOWN age
route delivery failures
node revocations
MCP transport errors
KORPUS verify failures after composition
material exposure volume
```

A spike is a hypothesis generator, not automatically a root cause.

---

## 24. Incident-to-regression conversion

Every meaningful incident should produce:

```text
incident observation
 -> minimal reproducer
 -> invariant violated
 -> regression test
 -> causal fix
 -> re-verification
```

If no reproducer can be built, the incident remains an unresolved unknown, not “fixed because it stopped happening”.

---

## 25. Learning-system analogy

The engineering loop has a useful abstract similarity to model training:

```text
examples / failures -> loss signal -> parameter/code/policy update -> reevaluation
```

But production engineering differs critically:
- many invariants are hard constraints, not average loss terms;
- one unauthorized execution can invalidate a release despite strong average metrics;
- the environment changes independently;
- evidence must bind exact software state.

Therefore optimize average quality only inside hard safety boundaries.

---

## 26. Release evidence packet

For each implementation candidate retain:

```text
subject SHA
source digest
OpenClaw version
Gateway/protocol version
MCP config identity
capability registry digest
mandatory eval results
negative controls
mutation result
clean-room result
runtime identity
known non-claims
```

A final verdict should be reconstructable without trusting chat transcripts.

---

## 27. Stop condition

An implementation phase is complete when:

```text
all frozen mandatory claims have executable PASS evidence
AND critical false-PASS mutants survived = 0
AND blocking unknown = 0
AND exact subject binding is current
```

Do not keep adding unrelated checks after this condition merely to increase the appearance of rigor.

---

## 28. Terminal principle

The system should become better through a disciplined feedback loop:

```text
measure reality
> challenge assumptions
> isolate mechanism
> make minimal correction
> falsify correction
> retain regression
> repeat
```

The quality bar is not “the agent looked intelligent”. The quality bar is **the system’s critical claims remain true under adversarial executable attempts to make them false**.
