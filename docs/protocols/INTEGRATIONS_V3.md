# Integration contracts v3

Every adapter has one-directional authority: it may supply data or transport evidence, but may not
alter identity, policy, source authority or claim support outside its port.

| Integration | Accepted input | Output | Timeout/retry | Fail state |
|---|---|---|---|---|
| OIDC/JWKS | bearer token, pinned issuer/audience/algorithms | verified claims | cached keys; bounded HTTP | 401, no dev fallback |
| S3 object store | bytes + expected SHA-256 | immutable content key | idempotent content address | ingestion aborts |
| Embedding service | minimized query/text + fixed model ID | normalized fixed-dimension vector | bounded HTTP; circuit-breakable | lexical-only only when profile explicitly permits semantic weight 0 |
| pgvector | authorized identity session + vector | span IDs and similarities | bounded top-k | no semantic candidates |
| PostgreSQL RLS | server-derived session attributes | filtered rows | transaction-scoped | query fails; no unrestricted retry |
| OpenTelemetry/Prometheus | low-cardinality operational events | traces/metrics | non-blocking export | application continues without changing answers |
| Remote audit anchor | monotonic sequence + signed head | independently persisted head | outbox replay + idempotency key | business event remains committed but operation surfaces anchor failure until reconciliation |

## Prohibited coupling

- Identity is never inferred from request body fields.
- Object storage metadata cannot approve a document.
- Embedding similarity cannot override access, temporal or review predicates.
- Telemetry labels cannot contain source text, query text, user IDs or corpus IDs.
- The audit anchor cannot be reset through the application control path.
- A provider outage cannot trigger a fallback to a less controlled provider.
