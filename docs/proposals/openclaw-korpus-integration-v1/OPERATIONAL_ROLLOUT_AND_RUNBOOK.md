# Operational Rollout, Pilot, and Rollback Runbook

**Status:** PROPOSED OPERATIONAL CONTRACT

This runbook defines how the integration moves from theory to pilot without granting broad autonomy by default.

---

## 1. Rollout philosophy

The rollout is staged by risk surface, not by feature enthusiasm.

```text
Phase 0  offline contract/eval
Phase 1  local read-only evidence
Phase 2  single-channel pilot
Phase 3  multi-channel read-only
Phase 4  bounded operational reads
Phase 5  one reversible bounded write class
Phase 6  transactional effects with reconciliation
Phase 7  selected node/device workflows
```

No phase is entered because the previous one “felt stable”. It requires explicit acceptance evidence.

---

## 2. Phase 0 — offline

Required:
- exact OpenClaw version selected;
- Gateway protocol version recorded;
- KORPUS exact SHA/source digest recorded;
- MCP tool schemas captured;
- integration config validated;
- negative-control suite runnable;
- no production credentials.

Exit gate:

```text
contract tests PASS
critical negative controls PASS
secrets absent
```

---

## 3. Phase 1 — local evidence client

Topology:

```text
local OpenClaw
 -> local KORPUS MCP
 -> local/pilot KORPUS API
```

Allowed tools only:

```text
korpus_grounds
korpus_ask
korpus_quote
korpus_verify
```

No nodes, writes, shell or unrelated external MCP servers required for this phase.

Exit gate:
- valid grounded workflow;
- unauthorized cases denied;
- no-ground distinct from transport failure;
- unsupported composition caught;
- token not exposed to model/logs;
- exact evidence captured.

---

## 4. Phase 2 — single-channel pilot

Select one channel/account and one bound operator identity.

Goals:
- prove route binding;
- prove delivery returns only to origin route;
- observe reconnect/session behavior;
- measure latency/failure modes.

Do not add multiple channels simultaneously; otherwise route defects become harder to isolate.

---

## 5. Phase 3 — multi-channel read-only

Add channels one at a time.

For each channel verify:
- exact account identity semantics;
- direct vs group behavior;
- thread/reply routing;
- message edits/deletions if material;
- attachment/media handling;
- retention/security constraints;
- data-class ceiling.

A passing Telegram integration does not authorize assuming WhatsApp/Slack/etc. have identical identity or privacy semantics.

---

## 6. Phase 4 — operational reads

Candidate capability examples:
- release status;
- runtime identity;
- permitted audit verification status;
- non-secret service health.

Each tool remains typed and narrow.

No generic shell.

---

## 7. Phase 5 — one bounded write

Choose a low-risk, reversible or safely idempotent effect.

Required before pilot:
- exact capability contract;
- exact resource binding;
- idempotency key;
- durable effect reservation;
- postcondition observable;
- reconciliation procedure;
- audit;
- rollback/compensation semantics;
- adversarial tests.

Do not enable multiple new effect classes at once.

---

## 8. Phase 6 — transactional effects

Required:
- `OUTCOME_UNKNOWN` state;
- bounded retries;
- reconciliation worker/path;
- operator visibility;
- incident procedure;
- per-capability blast-radius budget.

No success response from ambiguous effect state.

---

## 9. Phase 7 — nodes

Enable one node/device class at a time.

Required:
- paired node identity;
- command surface captured;
- local KORPUS mapping;
- data-class ceiling;
- revocation test;
- disconnect ambiguity handling;
- no hidden generic shell expansion.

---

## 10. Change control

Any change to these requires re-verification:

```text
OpenClaw version
Gateway protocol/client package
MCP transport mode
MCP tool schema
KORPUS release/source digest
route-binding policy
node command surface
model provider
channel account
side-effect capability semantics
```

---

## 11. Deployment identity packet

Record per deployment:

```text
integration build SHA
KORPUS SHA/source digest/release
OpenClaw release
Gateway protocol version
Gateway config digest
MCP config digest
capability registry digest
node registry digest if used
channel binding digest
```

---

## 12. Health checks

Health must distinguish:

```text
OpenClaw Gateway healthy
KORPUS MCP reachable
KORPUS API reachable
KORPUS authorization functional
KORPUS evidence path functional
channel delivery functional
node functional if used
```

One green process is not end-to-end health.

---

## 13. Synthetic probe

Maintain a safe non-sensitive probe workflow:

```text
known permitted question
 -> korpus_grounds
 -> korpus_ask
 -> verify
 -> no external side effect
```

Probe should use controlled fixture/data where possible.

Do not use a privileged real user’s content as generic health probe.

---

## 14. Runtime observability

Track:

```text
workflow latency
MCP call latency
KORPUS denial counts
no-ground counts
verify failures
transport failures
route mismatches
OpenClaw reconnects
schema drift events
OUTCOME_UNKNOWN count/age
reconciliation duration
```

Do not put secrets/corpus payloads in metric labels.

---

## 15. Audit review

Pilot review should sample:
- subject binding;
- capability/resource binding;
- policy decision reference;
- route identity;
- evidence identity;
- exact release;
- effect state where applicable.

A readable transcript is not enough if machine bindings are absent.

---

## 16. Incident severity

Suggested classes:

```text
P0 unauthorized effect / cross-subject leak / false-success critical effect
P0 verifier false-PASS on frozen critical invariant
P1 protected data delivered to wrong approved-but-unintended route
P1 repeated duplicate external effects
P1 audit loss for critical action
P2 availability/retry degradation without integrity loss
P3 UX/latency/non-critical presentation issue
```

Classification is proposal-local and should align with KORPUS release policy when implemented.

---

## 17. Emergency disable

Provide fast kill switches at multiple layers:

```text
OpenClaw agent/tool disable
MCP server disable/token revoke
KORPUS capability disable
route binding revoke
node revoke
external provider credential revoke
```

KORPUS capability disable is authoritative for KORPUS actions.

---

## 18. Kill-switch test

A kill switch not tested is not operational assurance.

Pilot must prove:
- disable propagates within declared time;
- stale sessions cannot continue protected operations;
- re-enable requires explicit action;
- audit records transition.

---

## 19. Rollback types

Distinguish:

```text
software rollback
configuration rollback
route-binding rollback
capability disable
external-effect compensation
```

Rolling back software does not undo external effects.

---

## 20. Software rollback

Before deploying new integration version:
- know previous compatible version;
- preserve schema/config compatibility plan;
- verify KORPUS release compatibility;
- know whether effect-ledger schema changed.

---

## 21. Configuration rollback

OpenClaw configuration may change tool exposure/routing.

Configuration should be versioned/digested so rollback is exact rather than manual recreation.

---

## 22. Incident workflow

```text
DETECT
 -> CONTAIN
 -> PRESERVE EVIDENCE
 -> CLASSIFY
 -> REPRODUCE
 -> FIX
 -> NEGATIVE CONTROL
 -> VERIFY
 -> DEPLOY
 -> MONITOR
```

Do not erase logs/effect state during cleanup before cause is understood.

---

## 23. Evidence preservation

For critical incident preserve:

```text
exact integration/KORPUS/OpenClaw versions
workflow/invocation ids
route binding
policy decision
effect ledger state
provider receipts
relevant audit records
schema/config digests
```

Avoid storing more protected payload than necessary.

---

## 24. Pilot success criteria

Phase A/B pilot should demonstrate:

```text
0 unauthorized executions
0 cross-route protected deliveries
0 unsupported KORPUS-grounded critical sentences
0 secret exposure
0 silent fallback from KORPUS outage to model memory
all critical negative controls PASS
stable bounded latency under declared workload
```

---

## 25. Pilot failure criteria

Immediate stop/containment if:
- wrong KORPUS subject binding;
- protected data crosses route/channel boundary;
- agent/provider metadata bypasses policy;
- side effect duplicated or ambiguous state misreported as success;
- tokens exposed to model/session/channel;
- verifier can false-PASS critical poison.

---

## 26. Promotion rule

```text
Promote(phase N -> N+1) iff
  current phase mandatory gates PASS
  ∧ critical findings closed
  ∧ blocking unknown = 0
  ∧ rollback/disable path tested
```

No promotion by elapsed time alone.

---

## 27. Autonomy promotion

Increasing autonomy level is a separate promotion event.

Example:

```text
read-only automatic
 -> bounded write recommendation
 -> bounded write automatic
```

Each step requires new effect-specific evidence.

---

## 28. External upgrade policy

Before OpenClaw upgrade:

```text
pin candidate version
review changelog/protocol changes
capture new tool/node schemas
run compatibility suite
run critical negative controls
canary in isolated environment
promote only after PASS
```

Do not auto-follow latest on production integration without validation.

---

## 29. KORPUS upgrade policy

A KORPUS source/release change invalidates exact-state evidence according to binding semantics.

Re-run integration acceptance for affected interfaces and security invariants.

---

## 30. Operational non-claims

Pilot success does not prove:
- all channels safe;
- all node commands safe;
- all future OpenClaw releases compatible;
- unrestricted autonomy safe;
- production HA/DR;
- external service availability.

State only what was measured.

---

## 31. Terminal principle

Rollout should maximize information gained per unit of new risk.

That means:

```text
small capability surface
+ strong observability
+ aggressive falsification
+ reversible deployment
+ explicit promotion gates
```

The fastest safe path is not to enable everything quickly. It is to isolate one uncertainty at a time until the integration’s behavior is mechanically predictable under the failures that matter.
