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
- an indeterminate reconciliation observation leaves the effect `OUTCOME_UNKNOWN`;
- reconciliation is compare-and-set from `OUTCOME_UNKNOWN` and has one terminal winner;
- provider reconciliation must query status only; it must never redispatch the original effect;
- automatic retry only if the same provider-side idempotency identity or equivalent proof
  prevents duplicate commitment.

Each capability declares compensation/rollback as provider-native, compensating action, or
none. Irreversibility must be explicit before execution.

Reconciliation recording is not a new authority plane. Any operator/API surface that invokes
it must first obtain canonical KORPUS authorization and must append canonical audit evidence;
the low-level reconciliation model alone grants no permission.
