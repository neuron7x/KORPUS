# Control Theory, Feedback, and Bounded Autonomy

**Status:** NORMATIVE THEORY FOR PROPOSAL v1

This document treats OpenClaw × KORPUS as a closed-loop control system over partially observed software, information and external-effect state. The goal is not metaphorical “agent autonomy”; the goal is controlled state transition under explicit authority and verification.

---

## 1. Control-system framing

Define:

```text
x_t  = true relevant system state at time t
o_t  = observed state available to controller
ĝ_t  = current goal / task specification
p_t  = canonical policy state
u_t  = proposed control action
ŷ_t  = predicted outcome
y_t  = observed outcome after execution
v_t  = verifier verdict
```

The integration loop is:

```text
observe -> infer task state -> propose -> authorize -> execute -> observe -> verify -> update
```

The controller is composite:

```text
Controller = ModelPlanner + DeterministicResolvers + KORPUSPolicy + EffectGuards + Verifier
```

No single component is assumed globally correct.

---

## 2. Separation of concerns

The system deliberately separates five functions:

### 2.1 Goal interpretation

Transforms human/channel input into candidate intent.

May be probabilistic.

### 2.2 Planning

Generates candidate decompositions and capability calls.

May be probabilistic.

### 2.3 Authorization

Determines whether a concrete subject/capability/resource transition is allowed.

Must be deterministic enough to audit and falsify.

### 2.4 Execution

Interacts with APIs, nodes, services or KORPUS operations.

May fail partially.

### 2.5 Verification

Compares postconditions/evidence against the requested and authorized transition.

Must not rely solely on the actor’s own narrative.

Thus:

```text
Plan != Permission
Permission != Execution
Execution != Success
SuccessClaim != VerifiedSuccess
```

---

## 3. Partial observability

A model never has the whole state.

Examples of hidden state:
- whether an upstream API applied a write before the TCP connection broke;
- whether a user’s KORPUS role changed after the OpenClaw session began;
- whether a node is still controlled by the same trusted device instance;
- whether a retrieved report is bound to the current source state;
- whether a channel delivery succeeded despite local timeout.

Therefore the integration must maintain explicit epistemic state:

```text
KNOWN_TRUE
KNOWN_FALSE
UNKNOWN
STALE
CONFLICTING
UNVERIFIED
```

A Boolean API that silently maps all non-true cases to false destroys information needed for safe recovery.

---

## 4. State estimator

For high-impact actions, build a state estimate from authoritative sources.

```text
x_hat_t = Estimate(
  KORPUS identity,
  KORPUS policy,
  exact release,
  resource version,
  effect ledger,
  OpenClaw route,
  node pairing state,
  provider observation
)
```

Trust ranking matters.

Suggested precedence:

```text
canonical KORPUS state
> cryptographically/content-bound evidence
> direct provider observation
> OpenClaw operational state
> model inference
> natural-language claim
```

A lower-ranked source may trigger remeasurement but must not silently override a higher-ranked authority.

---

## 5. Feedback types

### 5.1 Immediate execution feedback

Examples:
- HTTP status;
- MCP result;
- node RPC result;
- database transaction result.

Useful but insufficient for critical side effects.

### 5.2 Independent state feedback

Examples:
- GET/read-after-write on external resource;
- KORPUS audit readback;
- effect-ledger state;
- content digest recomputation.

This is the preferred postcondition evidence.

### 5.3 Delayed operational feedback

Examples:
- scheduled health check;
- delivery confirmation;
- reconciliation job;
- production telemetry.

### 5.4 Human feedback

Used for intent, approval or subjective success where no objective oracle exists.

Human approval does not waive machine-checkable technical invariants unless policy explicitly says so.

---

## 6. Autonomy ladder

The system uses a capability-specific autonomy ladder.

```text
L0  Observe only
L1  Recommend / draft only
L2  Execute read-only capability
L3  Execute reversible bounded write
L4  Execute transactional external effect with reconciliation
L5  Execute privileged authority-changing action
```

Default proposal scope:

```text
L2 enabled for KORPUS evidence tools after verification
L3 disabled until bounded-write controls exist
L4 disabled until effect ledger + OUTCOME_UNKNOWN + reconciliation exist
L5 denied; owner-controlled unless separately designed
```

This implements an “autonomy slider” structurally rather than rhetorically: different actions receive different control budgets.

---

## 7. Autonomy admission function

For capability `c` in context `x`:

```text
AutonomyAllowed(c, x, level) =
  PolicyAllows(c, x)
  ∧ RiskClass(c) <= MaxRisk(level)
  ∧ Reversibility(c) >= MinReversibility(level)
  ∧ Observability(c) >= MinObservability(level)
  ∧ IdentityConfidence(x) >= threshold
  ∧ ResourceBindingExact(x)
  ∧ EffectSemanticsKnown(c)
  ∧ VerificationAvailable(c)
```

For privileged operations, the required level may remain impossible for agents by design.

---

## 8. Stability

A useful control system should not oscillate between actions because of small, noisy state changes.

Examples of software oscillation:
- retry storms;
- repeated enable/disable operations;
- repeated channel routing changes;
- repeated deployment restarts;
- flip-flopping plan selection from nondeterministic model outputs.

Controls:
- idempotency keys;
- cooldowns where operationally valid;
- version/precondition checks;
- monotonic state transitions;
- explicit terminal states;
- bounded retries;
- hysteresis only where a metric genuinely fluctuates.

Do not add hysteresis to authorization. Permission should be derived from current policy, not “sticky trust”.

---

## 9. Retry theory

Retry is a control action, not generic error handling.

Decision table:

```text
READ + transient transport error
  -> bounded retry allowed

IDEMPOTENT WRITE + outcome known failed
  -> bounded retry allowed

IDEMPOTENT WRITE + outcome unknown
  -> reconcile first; retry only after proof

NON-IDEMPOTENT WRITE + outcome unknown
  -> never blind retry

AUTHORIZATION FAILURE
  -> do not retry without changed authority state

SCHEMA/POLICY FAILURE
  -> do not retry identical request
```

HTTP idempotency semantics are useful background, but capability semantics override naive method-based assumptions. A POST can be logically idempotent if the application explicitly binds an idempotency key; a superficially safe call may still trigger operational logging or billing.

Reference: RFC 9110 §9.2.2.

---

## 10. Outcome ambiguity

Define effect execution states:

```text
PENDING
COMMITTED
FAILED_KNOWN_NO_EFFECT
OUTCOME_UNKNOWN
RECONCILING
RECONCILED_COMMITTED
RECONCILED_NO_EFFECT
MANUAL_INTERVENTION_REQUIRED
```

The critical state is `OUTCOME_UNKNOWN`.

It means:

> The system cannot prove whether the external world changed.

This state is neither success nor failure.

Required behavior:
- preserve invocation identity;
- stop blind retries;
- run reconciliation;
- update canonical effect ledger;
- expose accurate state to user/operator.

---

## 11. Verification loop

For action `u_t`, define expected postcondition `Q`.

```text
Verify(u_t) = Compare(ObservedPostState, Q)
```

Strong verification uses a measurement path distinct from the execution response when feasible.

Examples:

```text
send_message
  execution evidence: provider accepted request
  stronger verification: provider message id / readback where supported

write_config
  execution evidence: API 200
  stronger verification: reread exact resource/version/digest

KORPUS evidence request
  execution evidence: tool result
  stronger verification: quote/span hashes + korpus_verify for composed draft
```

---

## 12. Negative feedback and containment

When verifier detects deviation:

```text
if unauthorized_effect:
    contain immediately
elif wrong_resource:
    stop related workflow + escalate
elif unknown_outcome:
    reconcile
elif output_unsupported:
    abstain/recompose
elif stale_binding:
    refresh from canonical source
```

The controller should reduce authority and action scope under uncertainty, not increase it.

---

## 13. Controller gain and blast radius

In classical control, excessive gain can destabilize a system. In agentic systems, the analogous variable is **action amplification**.

One user sentence can potentially fan out into:
- many tool calls;
- multiple agents;
- multiple nodes;
- many external writes.

Define amplification:

```text
Amp(workflow) =
  number_of_effectful_calls
  * number_of_resources
  * number_of_external_domains
  * concurrency_factor
```

This is diagnostic, not a universal formula.

Controls:
- per-workflow budgets;
- capability allowlists;
- max fan-out;
- max side effects;
- max parallel mutations;
- explicit approval above thresholds.

---

## 14. Control budgets

A workflow may have budgets:

```text
Budget = {
  max_tool_calls,
  max_effectful_calls,
  max_external_bytes,
  max_runtime_seconds,
  max_cost,
  max_nodes,
  max_retries,
  max_resources_mutated
}
```

Budget exhaustion is a named terminal condition, not a reason to silently bypass checks.

---

## 15. Agent decomposition

Multi-agent execution is justified only when it produces measurable value.

Potential benefits:
- parallel search;
- domain specialization;
- structural verification;
- isolation of write authority;
- clean-room reproduction.

Costs:
- coordination state;
- duplicated context;
- conflicting actions;
- authority propagation complexity;
- audit complexity.

Decision rule:

```text
UseMultiAgent iff
  ExpectedDecompositionBenefit
  > CoordinationCost + NewFailureSurface
```

Never use multiple agents only to make a workflow appear more sophisticated.

---

## 16. Route correctness

OpenClaw routing is part of the control loop because correct results sent to the wrong conversation are failures.

Define:

```text
DeliveryAuthorized(result, route) =
  route == bound_origin_route
  ∧ subject_binding_valid
  ∧ data_classification_permitted_on_channel
  ∧ no cross-session leakage
```

The system must distinguish:

```text
ActionAuthorized
ResultAuthorizedForDelivery
```

A result may be valid internally yet forbidden on the originating channel because the channel is not approved for that material class.

---

## 17. Channel as noisy sensor

Natural-language channels are noisy measurement surfaces.

Noise sources:
- forwarded messages;
- quoted text;
- group participants;
- bot mentions;
- edits;
- deleted context;
- partial media parsing;
- impersonation/social-engineering attempts.

Therefore channel content is treated as task input, not as security metadata unless a separately verified channel identity binding exists.

---

## 18. Node as actuator

OpenClaw nodes expose device-side commands. In control terms, a node is an actuator plus sensor surface.

Required separation:

```text
NodePaired != NodeAuthorizedForKorpusData
NodeCanExecute(command) != KorpusMayRequest(command)
```

Node policy must include:
- exact node identity;
- permitted command family;
- data classification ceiling;
- user/session binding;
- device state where relevant;
- revocation path.

---

## 19. Safe degradation

When dependencies fail:

```text
OpenClaw unavailable
  -> KORPUS remains independently usable

KORPUS unavailable
  -> OpenClaw must not fabricate KORPUS-grounded answers

MCP unavailable
  -> no silent substitution with model memory for protected facts

node unavailable
  -> workflow degrades to non-node path or explicit refusal

external write provider unavailable
  -> preserve effect state; do not fake completion
```

Dependency loss must reduce function, not integrity.

---

## 20. Learning loop

Operational improvement loop:

```text
observe failure
 -> classify failure mode
 -> build reproducer
 -> add negative control
 -> fix root cause
 -> verify exact candidate
 -> deploy boundedly
 -> observe recurrence rate
```

Do not optimize from anecdote alone.

A failure report becomes engineering knowledge only after it is bound to:
- input;
- state;
- expected behavior;
- observed behavior;
- reproducible mechanism.

---

## 21. Control invariants

Mandatory invariants:

```text
I1  model proposal cannot bypass KORPUS policy
I2  route identity cannot widen subject authority
I3  tool metadata cannot grant capability authority
I4  node pairing cannot widen data authority
I5  write retry cannot duplicate logical effect
I6  unknown external outcome cannot return success
I7  verification failure cannot be hidden by delivery success
I8  dependency failure cannot silently downgrade evidence rules
I9  control-plane convenience cannot override release identity
I10 canonical KORPUS audit remains reconstructable
```

---

## 22. Acceptance experiments

At minimum:

1. valid read workflow succeeds;
2. same workflow with unauthorized corpus fails;
3. same channel routed to wrong KORPUS principal fails;
4. valid MCP transport credential + forbidden logical capability fails;
5. node is paired but material class exceeds node ceiling -> fails;
6. external write times out after possible commit -> enters `OUTCOME_UNKNOWN`;
7. replay of idempotent write -> one logical effect;
8. verifier detects modified post-state;
9. OpenClaw unavailable -> KORPUS remains authoritative and independent;
10. KORPUS unavailable -> OpenClaw does not claim grounded KORPUS result.

---

## 23. Terminal principle

The integration should behave like a well-designed controller:

- observe before acting;
- act only within authority;
- prefer bounded, reversible actions;
- measure the actual post-state;
- reduce action under uncertainty;
- preserve enough state to recover from ambiguity;
- learn from falsifiable failures.

Autonomy is not the removal of control. Good autonomy is **control made explicit enough that routine actions can proceed without repeated human micromanagement while high-impact uncertainty remains bounded**.
