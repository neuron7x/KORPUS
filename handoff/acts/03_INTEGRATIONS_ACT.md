# Act 03 — implemented integration contracts

| Integration | Implemented contract | Current evidence boundary |
|---|---|---|
| OIDC/JWKS | issuer/audience/algorithm pinning, `kid`, cache and BFF browser flow | production IdP not connected |
| PostgreSQL/RLS | non-superuser/RLS design, migrations and integration test | live PostgreSQL test remains skipped locally |
| pgvector | optional authorized semantic candidates | no production embedding/index lifecycle proof |
| S3/MinIO | content addressing, checksums, prefix policy and object-lock configuration | production S3/KMS not connected |
| Embedding service | fixed model/dimension, timeout, retry and corpus-policy egress gate | semantic weight remains zero by default |
| OpenTelemetry/Prometheus | low-cardinality traces and metrics | durable production backend not connected |
| Remote audit anchor | monotonic checkpoint, HMAC contract and outbox reconciliation | independent production trust domain not connected |

No integration may weaken identity, policy, temporal validity, source authority or claim support. Provider failure never permits an uncontrolled fallback.
