# Observability and audit

Propagate W3C trace context across API, queue, retrieval and provider calls. Structured
events include request ID, pseudonymous actor ID, corpus/index versions, policy result,
retrieval run, evidence IDs, prompt/model version, latency, token/cost counters and
answer status.

Do not log raw credentials, source contents, full user documents or unnecessary query
text. Audit events are append-only and access-controlled; application telemetry is
shorter-lived and sampled separately.

Dashboards separate system reliability from epistemic quality. A 200 response with an
unsupported claim is a quality failure even when infrastructure is healthy.

