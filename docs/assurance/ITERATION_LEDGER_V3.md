# Iteration ledger v3

| Iteration | Structural delta | Killable gate |
|---|---|---|
| 1 | Explicit convex retrieval utility, MMR and deadlines | invalid weights, duplicate-version dominance and deadline overrun fail |
| 2 | Reproducible ranking tuner with nDCG/MRR/Recall | under-sampled or weak ranking profile cannot deploy |
| 3 | Risk-adaptive selective answering | temporal/operational risk cannot weaken thresholds |
| 4 | Identity/release/config-bound cache | restricted updates cannot perturb or populate public cache state |
| 5 | Admission control and circuit breaker | concurrency overload is rejected before resource collapse |
| 6 | OpenTelemetry and Prometheus | metrics exclude user, query and corpus identifiers from labels |
| 7 | Cached OIDC/JWKS verification | missing `kid`, wrong issuer/audience or unpinned algorithm fails |
| 8 | Checksum-verified immutable S3 storage | hash mismatch, metadata mismatch or failed retention fails |
| 9 | PostgreSQL FORCE RLS and pgvector fusion | inaccessible spans remain unavailable below application policy |
| 10 | Remote audit anchor and operational gate | truncation, anchor conflict or assurance regression blocks release |

## Integration map

1. OpenTelemetry trace export.
2. Prometheus bounded-cardinality metrics.
3. OIDC/JWKS identity verification.
4. S3-compatible immutable object storage.
5. pgvector semantic candidate index.
6. PostgreSQL row-level security.
7. Remote monotonic audit-anchor service.

## Evidence interpretation

Passing the ledger proves only encoded software predicates against the executed fixtures and
environment. It does not establish real-corpus authority, OCR fidelity, cybersecurity accreditation,
production capacity, legal rights, domain correctness or military authorization. Those require
separate evidence owners and operational trials.
