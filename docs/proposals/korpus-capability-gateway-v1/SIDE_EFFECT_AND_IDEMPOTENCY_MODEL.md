# Side Effects and Idempotency

Effectful classes require explicit authorization beyond normal read behavior.

## Binding

```text
H(
  subject_id,
  capability_id,
  capability_version,
  logical_resource,
  canonical_input_digest,
  idempotency_key
)
```

Durable states:
`PENDING`, `COMMITTED`, `FAILED_KNOWN_NO_EFFECT`, `OUTCOME_UNKNOWN`, `RECONCILED`.

`RECONCILED` is a transport/state-machine terminal, not a sufficient semantic outcome.
Every reconciled record additionally carries exactly one durable disposition:

- `CONFIRMED_COMMITTED` — provider reconciliation establishes that the original effect committed;
- `CONFIRMED_NO_EFFECT` — provider reconciliation establishes that the original effect did not commit.

A `RECONCILED` row without one of these dispositions is invalid. A non-reconciled row carrying
a reconciliation disposition is also invalid. This prevents ambiguity from being erased by a
semantically empty terminal label.

Rules:
- same key + same binding: replay/reconcile existing outcome, no duplicate effect;
- same key + different binding: `IDEMPOTENCY_CONFLICT`, no execution;
- timeout after dispatch: `OUTCOME_UNKNOWN`;
- reconciliation requires the exact subject, capability id/version, idempotency binding and
  compatible provider reference before a provider status observation is admitted;
- reconciliation additionally requires the server-owned `EffectSafetyDeclaration` to resolve
  exactly against the current immutable capability contract;
- automatic provider reconciliation must use the exact strategy declared by
  `reconciliation_mode`; a provider-status resolver cannot stand in for an idempotency lookup
  and vice versa;
- `MANUAL` reconciliation never invokes an automatic provider resolver. It requires a distinct
  canonical-authorized, canonical-audited operator workflow;
- resolver strategy identity is server composition, not provider/request metadata, and cannot
  widen authorization or select a different reconciliation mode;
- an indeterminate reconciliation observation leaves the effect `OUTCOME_UNKNOWN`;
- reconciliation is compare-and-set from `OUTCOME_UNKNOWN` and has one terminal winner;
- provider reconciliation must query status/lookup identity only; it must never redispatch the
  original effect;
- automatic retry only if the same provider-side idempotency identity or equivalent proof
  prevents duplicate commitment.

Each effectful capability has an exact-bound safety declaration. Compensation semantics are
validated over the complete server-owned capability graph, not as isolated strings:
- `PROVIDER_NATIVE` declares provider-native rollback semantics;
- `NONE` requires explicit irreversibility;
- `COMPENSATING_ACTION` requires an exact distinct capability id/version whose target is
  registered, `ENABLED`, and effectful;
- a compensating target remains an effectful capability in its own right and therefore must
  satisfy its own authorization, idempotency, evidence/audit and effect-safety constraints.

Let `C` be the finite set of enabled effectful capabilities and let `comp: C ⇀ C` map a
`COMPENSATING_ACTION` declaration to its exact compensation target. Structural recovery
admission requires:

```text
forall c in C: not (c (comp)+ c)
```

Therefore the compensation graph must be acyclic. Since each source has at most one target,
finite acyclicity makes every declared compensation chain terminate at a non-compensating
recovery node. A cycle such as `A -> B -> A` or `A -> B -> C -> A` is not a recovery plan and
blocks deployment/runtime composition fail-closed.

This well-foundedness property is deliberately narrow: it proves termination of the declared
recovery relation, not operational rollback success. It does not imply that provider-native
rollback will succeed, that a compensating action is semantically inverse, or that multi-step
compensation is atomic.

A named but missing, disabled, read-only, or cyclic compensation target is not rollback
readiness and blocks deployment/runtime composition fail-closed.

Reconciliation recording is not a new authority plane. Any operator/API surface that invokes
it must first obtain canonical KORPUS authorization and must append canonical audit evidence;
the low-level reconciliation model alone grants no permission.
