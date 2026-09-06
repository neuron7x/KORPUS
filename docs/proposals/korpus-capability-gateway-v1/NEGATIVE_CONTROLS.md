# Negative Controls

| Poison | Expected | Adapter calls |
|---|---|---:|
| nonexistent capability | `CAPABILITY_UNKNOWN` | 0 |
| policy deny | `POLICY_DENIED` | 0 |
| policy unknown/unavailable | fail closed | 0 |
| invalid capability input | `INPUT_SCHEMA_INVALID` | 0 |
| caller adds `authorized=true`, `role=admin` | schema reject/no authority gain | 0 |
| provider output violates schema | `OUTPUT_SCHEMA_INVALID` | 1 |
| required evidence missing | abstain/reject | 1 |
| stale evidence | `EVIDENCE_STALE` | 1 |
| evidence binds wrong invocation/output | `EVIDENCE_SUBJECT_MISMATCH` | 1 |
| adapter exception | stable `ADAPTER_FAILURE` + audit | 1 |
| effect without idempotency | `IDEMPOTENCY_REQUIRED` | 0 |
| same key, different binding | `IDEMPOTENCY_CONFLICT` | 0 |
| same key, same binding concurrent replay | <=1 external effect | controlled |
| effect timeout | `OUTCOME_UNKNOWN` | 1 |
| malicious MCP description | remains untrusted data | no automatic authority |
| incompatible MCP schema/effect drift | quarantine/disable | 0 |
| wrong provider/server identity | reject | 0 |
| required audit append failure | no success | depends on effect |
| wrong serving candidate/release | deployment gate fail | n/a |

Verifier quality requires clean pass + poisoned fail for intended reason + exact subject
binding. Missing/unknown is never success.
