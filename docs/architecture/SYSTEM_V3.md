# System architecture v3

> **HISTORICAL SNAPSHOT — NOT CURRENT SSOT.** Current architecture: `SYSTEM.md`.

## Value function

KORPUS optimizes a constrained operational utility, not answer volume:

```text
maximize:   verified task utility + evidence recall + operator throughput
minimize:   unsupported claims + unauthorized exposure + stale authority
            + latency + cost + recovery time + operational entropy
subject to: access noninterference, temporal validity, exact citation binding,
            deterministic release identity, bounded work, recoverable audit
```

No scalar score can compensate for a hard trust violation. Authorization, current-version
selection, evidence binding and audit integrity are lexicographic gates. Ranking weights are
optimized only inside the admissible evidence set.

## Runtime topology

```text
OIDC/JWKS cache + algorithm pinning
        |
server-derived Identity
        |
PostgreSQL session identity -> FORCE RLS
        |
lexical GIN/FTS5 ---- pgvector HNSW
        |                  |
        +--- bounded candidate fusion ---+
                         |
calibrated convex reranker + temporal/authority utility
                         |
MMR diversity + per-version cap + deadline
                         |
risk-adaptive selective answering
                         |
exact claim-to-span citation
                         |
SQL audit transaction -> outbox -> remote monotonic HMAC anchor
                         |
OpenTelemetry traces + low-cardinality Prometheus metrics
```

## Operational boundaries

- GitLab protected `main` is the code source of truth.
- PostgreSQL is metadata, policy-state, review-state and audit-event source of truth.
- S3-compatible content-addressed storage is raw-source truth; retrieval indexes are rebuildable.
- Remote audit anchor is outside the database failure domain.
- Cache keys bind subject, clearance, corpus set, date, configuration and corpus release.
- External integrations cannot widen authorization or create unsupported claims.
- A failed embedding, anchor, object-store, identity or telemetry dependency has an explicit
  fail-closed or degraded-mode contract; there is no silent fallback across trust levels.

## Scaling decisions

The modular monolith remains the trust kernel because policy, temporal selection, claim binding
and audit must share one consistency boundary. Independently scalable adapters are limited to
stateless embedding, object storage, identity, telemetry and remote anchoring. Service extraction
requires measured contention or independent scaling pressure, plus a contract and noninterference
proof; organizational preference is not sufficient evidence.

## Parameter discipline

- Ranking weights form a convex combination and are stored in a content-addressed calibration profile.
- BM25, semantic weight, candidate budget, MMR lambda, per-version cap and timeouts are calibrated
  together on frozen judged queries.
- Query-risk thresholds are monotone: operational and temporal queries cannot receive weaker gates.
- Local p95 probes are engineering evidence only, never a production SLA.
- Drift uses Jensen-Shannon divergence over fixed-bin score/status distributions; a threshold is not
  valid until a real baseline has at least the configured observation minimum.
