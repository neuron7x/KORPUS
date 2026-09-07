# State Machines

## Invocation

```text
RECEIVED
 -> RESOLVED
 -> AUTHORIZED
 -> INPUT_VALID
 -> EFFECT_GUARDED
 -> EXECUTING
 -> OUTPUT_VALID
 -> EVIDENCE_VALID_OR_NOT_REQUIRED
 -> AUDITED
 -> RETURNED
```

Terminal states:
- `DENIED` — policy/lifecycle refusal;
- `REJECTED` — invalid contract/effect/evidence;
- `FAILED` — runtime/provider/audit failure;
- `ABSTAINED` — factual/critical evidence requirement not satisfied;
- `OUTCOME_UNKNOWN` — effect may have committed but transport outcome is ambiguous.

Forbidden transitions include `RECEIVED -> EXECUTING`, any execution before authorization,
and any required-evidence/audit bypass to success.

Authority is monotonic: later stages may reduce returnability, never broaden permission.
