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

Rules:
- same key + same binding: replay/reconcile existing outcome, no duplicate effect;
- same key + different binding: `IDEMPOTENCY_CONFLICT`, no execution;
- timeout after dispatch: `OUTCOME_UNKNOWN`;
- automatic retry only if the same provider-side idempotency identity or equivalent proof
  prevents duplicate commitment.

Each capability declares compensation/rollback as provider-native, compensating action, or
none. Irreversibility must be explicit before execution.
