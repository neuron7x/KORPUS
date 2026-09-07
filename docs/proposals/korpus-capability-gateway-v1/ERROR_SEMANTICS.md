# Error Semantics

| Code | External call | Default outcome |
|---|---:|---|
| `CAPABILITY_UNKNOWN` | no | DENIED/REJECTED |
| `CAPABILITY_DISABLED` | no | DENIED |
| `POLICY_DENIED` | no | DENIED |
| `POLICY_UNKNOWN` | no | FAILED_CLOSED |
| `INPUT_SCHEMA_INVALID` | no | REJECTED |
| `EFFECT_AUTH_REQUIRED` | no | DENIED |
| `IDEMPOTENCY_REQUIRED` | no | REJECTED |
| `IDEMPOTENCY_CONFLICT` | no | REJECTED |
| `ADAPTER_TIMEOUT` | yes/unknown | FAILED or OUTCOME_UNKNOWN |
| `ADAPTER_FAILURE` | yes/unknown | FAILED |
| `OUTPUT_SCHEMA_INVALID` | yes | FAILED_CLOSED |
| `EVIDENCE_MISSING` | yes | ABSTAINED/REJECTED |
| `EVIDENCE_INVALID` | yes | ABSTAINED/REJECTED |
| `EVIDENCE_STALE` | yes | ABSTAINED/REJECTED |
| `EVIDENCE_SUBJECT_MISMATCH` | yes | FAILED_CLOSED |
| `AUDIT_APPEND_FAILED` | maybe | FAILED_CLOSED |
| `RUNTIME_IDENTITY_UNKNOWN` | no/unknown | FAILED_CLOSED |
| `INTERNAL_ERROR` | unknown | FAILED |

Raw provider errors, credentials, tokens, restricted bodies and stack traces are not
user-visible by default. Effectful timeout is never proof of no effect.
