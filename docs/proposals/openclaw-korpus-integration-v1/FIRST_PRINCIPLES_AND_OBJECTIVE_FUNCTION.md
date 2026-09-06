# First-Principles System Model and Objective Function

**Status:** NORMATIVE THEORY FOR PROPOSAL v1  
**Purpose:** define what the OpenClaw × KORPUS integration is optimizing, what it is forbidden to trade away, and how design decisions are derived from primitives rather than product labels.

---

## 0. Method

This document deliberately starts below product names.

The integration is not designed by asking:

> “What can OpenClaw do?”

It is designed by asking:

1. What state exists?
2. What observations are trustworthy?
3. What actions are possible?
4. Who is authorized to choose each action?
5. What can fail before, during and after execution?
6. What evidence would falsify a claim of correctness?
7. Which objectives are optimizable and which constraints are non-negotiable?

That order matters. Product affordances change. System invariants must survive product change.

A useful pedagogical analogy is the “build from primitives, make every transformation explicit, test each abstraction” style used in Andrej Karpathy’s *Neural Networks: Zero to Hero*: complex behavior is easier to reason about when the small mechanisms underneath it are visible. His 2025 *Software Is Changing (Again)* talk also emphasizes partial autonomy, human–AI collaboration loops, and building digital infrastructure for agents. Those sources motivate the explanatory style here; they are **not** treated as security standards or implementation authority.

References:
- https://karpathy.ai/zero-to-hero.html
- https://github.com/karpathy/nn-zero-to-hero
- https://www.youtube.com/watch?v=LCEmiRjPEtQ

---

## 1. Primitive objects

Let the system contain the following primitive domains.

### 1.1 Subject

A **subject** is the KORPUS principal whose authority is evaluated.

```text
Subject = {
  subject_id,
  account_id,
  roles,
  clearance,
  corpora,
  compartments,
  entitlement,
  session_security_state
}
```

OpenClaw user/channel/session identity may help resolve which KORPUS subject is being requested, but it is not itself the final KORPUS authority fact.

### 1.2 Route

A **route** is an orchestration/delivery context.

```text
Route = {
  gateway_id,
  agent_id,
  channel,
  account,
  peer,
  session_id,
  node_id?,
  thread_or_conversation_id?
}
```

Route answers **where an interaction came from and where a response may return**. It does not answer **what the subject may do**.

### 1.3 Capability

A **capability** is a locally defined logical operation.

```text
Capability = {
  capability_id,
  version,
  action,
  resource_type,
  effect_class,
  input_schema,
  output_schema,
  egress_policy,
  evidence_policy,
  retry_policy,
  timeout_policy,
  audit_policy
}
```

The local KORPUS definition owns the meaning. A remote tool name is not a capability grant.

### 1.4 Resource

A **resource** is the object over which authorization is evaluated.

Examples:
- corpus/document/span;
- conversation;
- account;
- release state;
- deployment observation;
- bounded external object;
- device command target.

A request that cannot bind to a sufficiently exact resource is not authorized merely because its verb looks familiar.

### 1.5 Evidence

Evidence is a source-bound object capable of supporting or falsifying a factual claim.

```text
Evidence = {
  evidence_id,
  subject_binding,
  source_identity,
  content_identity,
  temporal_validity,
  provenance,
  admissibility,
  verification_state
}
```

Agent memory, OpenClaw session history, model output and tool descriptions are not automatically evidence.

### 1.6 Effect

An **effect** is an externally observable state transition caused by a capability.

```text
Effect = {
  logical_resource,
  desired_transition,
  idempotency_key,
  precondition,
  execution_state,
  postcondition,
  reconciliation_state
}
```

A write is not defined by HTTP method alone. It is defined by whether the external world can change.

---

## 2. System state

At time `t`, define the integration state:

```text
X_t = (
  S_t,   # KORPUS subject
  R_t,   # OpenClaw route/session
  C_t,   # exact capability registry state
  P_t,   # canonical policy state
  E_t,   # admissible evidence state
  F_t,   # external effect state
  A_t,   # canonical audit state
  D_t,   # deployment/runtime identity
  L_t    # release identity
)
```

The system never observes `X_t` perfectly. It receives an observation `O_t` from channels, OpenClaw, MCP/API transport, KORPUS runtime, databases and external providers.

Therefore:

```text
Observation != State
```

and:

```text
Unknown(state component) != Safe default
```

For a security- or effect-relevant unknown, the default transition is refusal, containment or reconciliation.

---

## 3. Action space

Let an orchestration model or deterministic controller propose an action `a` from action space `A`.

Partition `A`:

```text
A = A_read_evidence
  ∪ A_read_operational
  ∪ A_write_bounded
  ∪ A_transactional
  ∪ A_privileged
```

### 3.1 Read/evidence

Examples:
- `korpus_grounds`;
- `korpus_ask`;
- `korpus_quote`;
- `korpus_verify`.

No protected KORPUS state mutation is intended.

### 3.2 Operational read

Examples:
- exact release status;
- health/status permitted to the subject;
- audit verification result;
- deployment observation through a read-only probe.

These can still leak sensitive information and therefore remain authorization- and egress-governed.

### 3.3 Bounded write

A narrow mutation with explicit object identity, bounded semantics and idempotency.

### 3.4 Transactional side effect

An action whose success/failure must be reconciled against external state when transport outcome is ambiguous.

### 3.5 Privileged action

Release signing, secret management, unrestricted shell, arbitrary database mutation or authority-changing operation.

These are denied by default and are outside v1 unless separately authorized.

---

## 4. Hard constraints before utility

A common design error is to compress everything into one scalar “utility” and allow enough benefit to outweigh a safety violation.

KORPUS must not do this.

Use **constrained lexicographic optimization**.

First define admissibility:

```text
H(a, X_t) =
  AuthenticatedSubject
  ∧ ExactCapabilityResolved
  ∧ ResourceBound
  ∧ CanonicalPolicyAllow
  ∧ InputValid
  ∧ EgressValid
  ∧ EffectGuardSatisfied
  ∧ RequiredEvidenceAvailable
  ∧ AuditPathAvailable
```

Only actions with:

```text
H(a, X_t) = TRUE
```

enter the utility optimization set.

Thus:

```text
A_admissible(X_t) = { a ∈ A | H(a, X_t) = TRUE }
```

If `A_admissible = ∅`, the correct output is abstention/refusal/escalation, not a lower-confidence execution.

---

## 5. Objective function

Among admissible actions, choose actions that maximize useful task value while minimizing operational cost and uncertainty.

A diagnostic scalar objective may be written:

```text
J(a | X_t) =
    + w_g * GoalProgress(a)
    + w_q * AnswerOrActionQuality(a)
    + w_v * Verifiability(a)
    + w_r * Reversibility(a)
    + w_o * Observability(a)
    - w_l * Latency(a)
    - w_c * MonetaryComputeCost(a)
    - w_b * BlastRadius(a)
    - w_u * ResidualUncertainty(a)
    - w_e * EvidenceDeficit(a)
    - w_x * ExternalExposure(a)
```

This scalar is **not** release authority. It is a reasoning instrument after hard constraints already passed.

The important architectural point is:

```text
Safety invariants are constraints, not weights.
```

A high `GoalProgress` cannot compensate for unauthorized access.

---

## 6. Value hierarchy

For KORPUS, the objective hierarchy is:

### Tier 0 — Authority correctness

Never perform an operation because an agent, channel, node, MCP server or provider says it is authorized.

### Tier 1 — Evidence correctness

Never present unsupported critical factual content as supported.

### Tier 2 — Effect correctness

Never return success for a side effect whose material outcome is unknown.

### Tier 3 — Auditability

Critical actions must leave enough canonical evidence to reconstruct who requested what, under which policy, against which resource and with which result.

### Tier 4 — Availability and latency

Optimize speed only after Tiers 0–3 remain satisfied.

### Tier 5 — Convenience

Channel ubiquity, natural-language control and automation are valuable only if they preserve higher tiers.

This produces an explicit ordering:

```text
Authority > Evidence > Effect certainty > Auditability > Availability > Convenience
```

---

## 7. Partial autonomy, not binary autonomy

Autonomy is not a boolean property of the entire system.

Define an autonomy level per capability and context:

```text
LoA(c, x) ∈ {0,1,2,3,4}
```

Suggested semantics:

```text
0 = suggest only
1 = read/observe automatically
2 = execute reversible low-risk action automatically
3 = execute bounded write under explicit policy + reconciliation
4 = privileged/high-impact autonomous execution
```

For v1:

```text
LoA(read/evidence) <= 1
LoA(bounded side effect) = 0 until effect controls are verified
LoA(privileged) = 0
```

The level may depend on:

```text
risk
resource sensitivity
identity confidence
reversibility
blast radius
observability
provider reliability
current incident state
```

This follows a first-principles view of autonomy: **grant only as much autonomous action as can be bounded and verified**.

---

## 8. Proposal vs authority

An LLM can be excellent at proposing candidate actions. Proposal generation and authority are different computational functions.

```text
Proposal = π_model(O_t, goal, context)
Authorization = π_policy(Subject, Capability, Resource, State)
```

Therefore:

```text
π_model != π_policy
```

and no prompt engineering should attempt to merge them.

The model may generate:
- intent;
- candidate capability;
- candidate arguments;
- clarification question;
- decomposition plan.

KORPUS must independently derive:
- exact capability;
- exact resource;
- permitted action;
- permitted data exposure;
- required evidence;
- effect constraints.

---

## 9. Information-flow objective

For protected information, minimize unnecessary data movement.

Let:

```text
M_required = minimal material necessary to satisfy admitted action
M_sent     = material actually exposed outside KORPUS boundary
```

Required property:

```text
M_sent ⊆ M_authorized
```

Optimization target:

```text
minimize |M_sent|
subject to TaskSatisfied = TRUE
```

This matters because OpenClaw may connect channels, models, nodes and MCP servers. The orchestration graph can be broad while the information graph remains narrow.

---

## 10. Uncertainty model

Not all uncertainty has equal meaning.

Partition uncertainty:

```text
U = U_intent
  ∪ U_identity
  ∪ U_authority
  ∪ U_resource
  ∪ U_evidence
  ∪ U_execution
  ∪ U_delivery
```

Treatment:

- `U_intent`: clarify or choose a non-destructive read.
- `U_identity`: refuse protected operation.
- `U_authority`: refuse.
- `U_resource`: refuse mutation; allow only safely bounded discovery if policy allows.
- `U_evidence`: abstain on critical factual claim.
- `U_execution`: enter `OUTCOME_UNKNOWN` and reconcile.
- `U_delivery`: do not repeat non-idempotent action merely because response delivery failed.

The system must name uncertainty rather than flatten it into “error”.

---

## 11. Expected-loss model for effectful actions

For a candidate effectful action, define:

```text
ExpectedLoss(a) =
    P(unauthorized_effect) * Impact_unauthorized
  + P(duplicate_effect)    * Impact_duplicate
  + P(wrong_resource)      * Impact_wrong_resource
  + P(outcome_unknown)     * Impact_ambiguity
  + P(data_exposure)       * Impact_exposure
  + P(non_recoverable)     * Impact_non_recoverable
```

This should not be treated as precise actuarial truth unless probabilities are measured. Its use is structural: it forces each failure mode to be named and instrumented.

An action class should not be automated until the system can materially bound the dominant terms.

---

## 12. Decision relevance

A proposed check belongs to current implementation/release only if its result can change a decision.

```text
DecisionRelevant(T) := ∃ outcome(T) : Decision changes
```

Examples:

- Can stale OpenClaw route identity cause wrong KORPUS subject binding? **Decision-relevant.**
- Can a new CSS theme drift? Not relevant to authority unless it hides/refactors a critical approval state.
- Can a tool description inject privileged instructions? **Decision-relevant** if descriptions reach the agent/system instruction boundary.
- Can an unneeded telemetry label be prettier? Not release-critical.

This prevents infinite assurance expansion.

---

## 13. Falsifiability as a design requirement

For every important positive claim `C`, define a poison `P` that should make it false.

```text
Claim(C) is release-usable only if:
  positive_fixture -> PASS
  falsifying_fixture -> FAIL
```

Examples:

```text
Claim: channel route cannot grant corpus authority
Poison: same channel identity, different unauthorized KORPUS corpus
Expected: FAIL

Claim: MCP token cannot authorize logical action
Poison: valid transport token, unauthorized capability/resource
Expected: FAIL

Claim: side effect is idempotent
Poison: replay exact invocation after ambiguous transport failure
Expected: one logical effect

Claim: evidence is source-bound
Poison: same path, different bytes/source digest
Expected: FAIL
```

A gate that has never been forced to fail is only an assertion about itself.

---

## 14. Simplicity objective

Complexity is not neutral. Every added policy layer creates:
- another state space;
- another drift surface;
- another failure mode;
- another place for authority semantics to diverge.

Therefore prefer:

```text
one canonical KORPUS policy plane
one canonical audit truth
one capability registry
one effect ledger
one release identity
```

OpenClaw policy may narrow what the agent can attempt, but it cannot widen KORPUS policy.

This is defense in depth without parallel authority.

---

## 15. Bounded optimization loop

The integration control loop is:

```text
OBSERVE
  -> PARSE INTENT
  -> PROPOSE
  -> RESOLVE EXACT CAPABILITY
  -> BIND RESOURCE
  -> AUTHORIZE
  -> VALIDATE INPUT/EGRESS/EFFECT
  -> EXECUTE
  -> OBSERVE RESULT
  -> VERIFY
  -> AUDIT
  -> UPDATE SESSION/PLAN
```

No step is decorative.

If any step required by the action class is unavailable, later steps cannot compensate.

---

## 16. Non-claims

This theory does not claim:
- numerical weights in `J` are currently calibrated;
- OpenClaw is safe merely because it has tool profiles;
- KORPUS can infer perfect human intent;
- a model can certify its own correctness;
- all side effects are compensatable;
- all OpenClaw versions preserve the same protocol semantics;
- formal notation proves implementation correctness.

The notation exists to make contradictions visible and tests derivable.

---

## 17. Acceptance consequences

An implementation consistent with this document must demonstrate:

1. authorization is a hard constraint outside model choice;
2. external routing identity cannot widen KORPUS authority;
3. remote tool metadata cannot create executable authority;
4. read/evidence tools are materially narrower than side-effect tools;
5. effectful actions have explicit idempotency and ambiguous-outcome semantics;
6. evidence and audit are bound to exact subjects/content/state;
7. autonomy is capability- and risk-dependent;
8. each critical claim has a falsifying negative control;
9. OpenClaw is replaceable as orchestration without changing KORPUS authority semantics;
10. the system can abstain/refuse when admissible action set is empty.

---

## 18. Core theorem

The highest-level integration theorem is:

```text
UsefulAutomation =
    HighQualityProposal
    ∩ ExactAuthority
    ∩ BoundedInformationFlow
    ∩ BoundedEffects
    ∩ VerifiableEvidence
    ∩ CanonicalAudit
```

Remove any intersection term and the system may remain convenient, but it is no longer the KORPUS-governed integration defined by this proposal.
