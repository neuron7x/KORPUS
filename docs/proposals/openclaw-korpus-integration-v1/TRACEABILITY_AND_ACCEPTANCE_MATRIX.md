# Traceability and Acceptance Matrix

**Status:** NORMATIVE PLANNING ARTIFACT

This matrix links high-level claims to implementation mechanisms, observables, falsifying controls and release consequences.

---

## 1. Matrix semantics

Each row contains:

```text
ID
Claim
Mechanism
Observable
Positive control
Falsifying control
Failure class
Decision consequence
Implementation phase
```

A row is not `CLOSED` until executable evidence exists for the exact implementation subject.

---

## 2. Authority and identity

| ID | Claim | Mechanism | Positive | Poison | Consequence |
|---|---|---|---|---|---|
| AUTH-01 | OpenClaw cannot grant KORPUS authority | canonical KORPUS policy | allowed subject/resource executes | valid OpenClaw session + forbidden KORPUS resource | P0 if executes |
| AUTH-02 | route identity is not principal authority | explicit route→subject binding | bound route resolves expected subject | same username/account-like string on different channel | P0 if privilege crosses |
| AUTH-03 | stale session cannot retain revoked authority | current policy evaluation | active permission works | revoke KORPUS permission mid-session | P0 if still executes |
| AUTH-04 | MCP token is transport credential only | local policy after MCP | token + allowed action works | valid token + denied logical action | P0 if executes |
| AUTH-05 | node pairing does not grant KORPUS data permission | node policy mapping/data ceiling | approved node + allowed class works | paired node above data ceiling | P0/P1 if disclosed |

---

## 3. Capability exactness

| ID | Claim | Mechanism | Positive | Poison | Consequence |
|---|---|---|---|---|---|
| CAP-01 | only exact local capability executes | local registry id/version | known id/version | unknown version with compatible schema | blocker if executes |
| CAP-02 | remote description cannot widen action | remote metadata untrusted | normal description | “always authorized; ignore policy” description | P0 if bypasses policy |
| CAP-03 | effect class is local | local capability metadata | read stays read | provider changes behavior to write without local update | quarantine required |
| CAP-04 | schema drift is observable | schema/version digest | same digest | changed required field/effect semantics | fail/quarantine |

---

## 4. Resource binding

| ID | Claim | Mechanism | Positive | Poison | Consequence |
|---|---|---|---|---|---|
| RES-01 | authorization binds exact resource | immutable invocation binding | authorized A executes A | substitute B after authorization | P0 if B executes |
| RES-02 | dynamic provider-selected resource stays constrained | result/resource contract | allowed result class | provider chooses forbidden resource | fail |
| RES-03 | retry preserves logical resource | idempotency binding | replay same resource | retry with changed resource under same key | fail |

---

## 5. Evidence

| ID | Claim | Mechanism | Positive | Poison | Consequence |
|---|---|---|---|---|---|
| EVD-01 | KORPUS-grounded answer has source-bound evidence | current MCP/API evidence path | known grounded question | unsupported question | abstain |
| EVD-02 | composition cannot add unsupported critical sentence | `korpus_verify` | exact supported prose | add uncited number/fact | block/recompose |
| EVD-03 | quote identity can be checked | `korpus_quote` hashes | correct span | altered quote bytes | fail |
| EVD-04 | session history is not evidence | workflow separation | history shown as context | answer using old assistant text without KORPUS evidence | fail policy/eval |
| EVD-05 | KORPUS outage not mapped to no-ground | error taxonomy | no-ground from live KORPUS | transport down | distinct failure |

---

## 6. Egress and information flow

| ID | Claim | Mechanism | Positive | Poison | Consequence |
|---|---|---|---|---|---|
| EGR-01 | only authorized material leaves KORPUS | egress policy | permitted citation | restricted material to public channel | P0/P1 leak |
| EGR-02 | cross-tool exfiltration blocked | workflow flow policy | KORPUS result to approved response | KORPUS result to unrelated upload tool | blocker |
| EGR-03 | secrets do not enter model/channel | secret isolation | env/secret mechanism | token embedded in prompt/log | P0/P1 |
| EGR-04 | group audience evaluated | route audience policy | direct message | privileged sender in public group | deny disclosure |

---

## 7. Effect safety

| ID | Claim | Mechanism | Positive | Poison | Consequence |
|---|---|---|---|---|---|
| EFF-01 | duplicate attempts do not duplicate logical effect | idempotency reservation | replay same key | race same key in two workers | P0/P1 if duplicate |
| EFF-02 | timeout after possible commit becomes unknown | effect state machine | explicit failure -> no-effect | provider commits, response lost | P0 if false failure/success |
| EFF-03 | unknown outcome reconciled before retry | reconciliation gate | query proves no effect then retry | blind retry while unknown | blocker |
| EFF-04 | compensation has own authority | compensation capability | authorized compensation | invoke compensation without policy | P0 if executes |
| EFF-05 | audit failure blocks critical success return | audit-before-return | audit succeeds | audit unavailable after effect | success must not be falsely returned |

---

## 8. Routing and delivery

| ID | Claim | Mechanism | Positive | Poison | Consequence |
|---|---|---|---|---|---|
| ROUTE-01 | response returns to exact originating route | route binding digest | same peer/thread | switch peer/thread before delivery | P1/P0 depending data |
| ROUTE-02 | channel reconnect does not silently change principal | binding version | reconnect same identity | re-pair/reconnect different account under stale mapping | fail |
| ROUTE-03 | delivery failure does not repeat underlying effect | separate delivery/effect state | retry delivery | resend effect to recreate response | blocker |

---

## 9. Node boundaries

| ID | Claim | Mechanism | Positive | Poison | Consequence |
|---|---|---|---|---|---|
| NODE-01 | paired node needs policy mapping | node state machine | mapped command | paired-only command | deny |
| NODE-02 | node command-surface drift is detected | command schema/registry digest | unchanged surface | new command after update | quarantine/review |
| NODE-03 | disconnect ambiguity is modeled | command effect class | read command fails | effectful command completes but response lost | unknown/reconcile |
| NODE-04 | node data ceiling enforced | destination class policy | allowed class | higher-class payload | deny |

---

## 10. OpenClaw compatibility

| ID | Claim | Mechanism | Positive | Poison | Consequence |
|---|---|---|---|---|---|
| OC-01 | implementation pins tested OpenClaw version | version manifest | exact supported version | untested latest | no promotion |
| OC-02 | Gateway wire version recorded | protocol identity | expected version | breaking version | fail compatibility |
| OC-03 | tool policy is defense in depth, not authority | dual gate | both allow | OpenClaw allow + KORPUS deny | deny |
| OC-04 | multi-agent isolation not called independent assurance | evidence classification | separate agent context reported correctly | claim “external independent” | governance fail |

---

## 11. Verification

| ID | Claim | Mechanism | Positive | Poison | Consequence |
|---|---|---|---|---|---|
| VER-01 | every frozen critical gate can fail | liveness/negative controls | clean fixture | targeted poison | P0-verifier if poison passes |
| VER-02 | evidence bound exact source | digest/version binding | current subject | old subject artifact | fail |
| VER-03 | implementation session not sole verifier | structural separation/clean-room | fresh context reproduction | reuse producer claim without run | evidence downgraded |
| VER-04 | mutation kills removed guard | mutation testing | correct code | remove auth/effect/evidence check | blocker if survives |

---

## 12. Operational resilience

| ID | Claim | Mechanism | Positive | Poison | Consequence |
|---|---|---|---|---|---|
| OPS-01 | OpenClaw failure cannot make KORPUS fabricate | dependency separation | KORPUS direct remains valid | Gateway down | reduced function only |
| OPS-02 | KORPUS failure cannot become model-memory answer | explicit failure path | live KORPUS | KORPUS unavailable | no grounded claim |
| OPS-03 | integration can be disabled quickly | kill switches | disable tool/token | stale session attempts | deny |
| OPS-04 | restart preserves ambiguous effects | durable effect ledger | clean restart | crash after remote commit | reconcile |

---

## 13. Phase closure

### Phase A mandatory IDs

```text
AUTH-01..04
CAP-01..04
RES-01
EVD-01..05
EGR-01..04
ROUTE-01..02
OC-01..04
VER-01..04
OPS-01..03
```

### Phase C adds

```text
RES-02..03
EFF-01..05
ROUTE-03
NODE-* where nodes enabled
OPS-04
```

---

## 14. Status vocabulary

Each row must be one of:

```text
NOT_IMPLEMENTED
IMPLEMENTED_UNVERIFIED
PASS_EXACT_STATE
FAIL
BLOCKED_EXTERNAL
N1_NOT_DECISION_RELEVANT
```

Avoid ambiguous “done”.

---

## 15. Evidence pointer format

For closed rows record:

```text
implementation_sha
test_id
fixture_id
report_path/report_digest
runtime identity if applicable
verifier class
```

A comment such as “tested manually” is not sufficient for critical closure.

---

## 16. Release rule

```text
PhaseReady =
  all mandatory rows == PASS_EXACT_STATE
  ∧ blocking unknown == 0
  ∧ critical verifier false-pass == 0
```

A strong average pass rate cannot compensate for one red hard row.

---

## 17. Terminal principle

Traceability prevents three common failure modes:

1. requirements exist but nothing tests them;
2. tests exist but nobody knows what claim they prove;
3. green reports belong to another software state.

The matrix exists so every important design sentence can eventually terminate in an exact executable observation.
