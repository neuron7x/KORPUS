# Observability

Recommended spans:
- `korpus.capability.invoke`
- `korpus.capability.policy`
- `korpus.capability.adapter`
- `korpus.capability.evidence`
- `korpus.capability.audit`
- `korpus.capability.reconcile`

Bounded attributes may include capability id/version, adapter id/version, effect class,
outcome, stable error type, policy/evidence outcome and release identity.

Do not attach raw prompts, corpus text, tokens, secrets, arbitrary response JSON or
high-cardinality user data.

Metrics: invocation outcomes, policy denies, contract rejects, adapter latency/errors,
evidence rejects, schema drift, `OUTCOME_UNKNOWN`, reconciliation latency.

Telemetry is sampled/lossy operational evidence. It cannot substitute for canonical audit.
