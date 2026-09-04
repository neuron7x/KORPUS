# Example Execution Traces

## Valid read

```text
RECEIVED I1
RESOLVED reference.public.read@1.0.0 -> http.reference@1.0.0
AUTHORIZED policy=pd1:...
INPUT_VALID digest=...
EFFECT_GUARDED READ_REMOTE
EXECUTING
OUTPUT_VALID digest=...
EVIDENCE_VALID binding=(I1, output_digest)
AUDITED A1
RETURNED SUCCESS
```

## Policy denial

```text
RECEIVED -> RESOLVED -> POLICY_DENIED
adapter_calls=0
```

## Effect timeout

```text
AUTHORIZED -> IDEMPOTENCY_BOUND K -> DISPATCH
transport timeout -> OUTCOME_UNKNOWN
reconcile(K) -> COMMITTED | FAILED_KNOWN_NO_EFFECT
```

## MCP schema drift

```text
approved digest D1, READ_REMOTE
observed digest D2 with incompatible/broader contract
=> local capability QUARANTINED
=> execution count 0 until revalidation
```
