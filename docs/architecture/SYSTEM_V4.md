# KORPUS infrastructure-hardened architecture — v4

> **HISTORICAL SNAPSHOT — NOT CURRENT SSOT.** Current architecture: `SYSTEM.md`.

## Trust boundaries

```text
host:127.0.0.1:3000
        |
        v
non-root nginx/PWA -- internal edge -- API
                                      |-- internal backend --> PostgreSQL/pgvector
                                      |                    --> MinIO/S3
                                      |                    --> OTel collector
                                      `-- dedicated egress --> OIDC / embedding / remote anchor
```

Only the web proxy publishes a host port. Backend networks are internal. The API is the only service attached to the egress network.

## Startup order

1. PostgreSQL reports healthy.
2. Alembic upgrades to the exact repository revision.
3. A non-superuser application role with explicit grants and forced RLS is prepared.
4. MinIO creates a versioned object-lock bucket and a prefix-scoped application identity.
5. The collector validates its configuration.
6. The API validates schema, object storage and audit-anchor state through readiness.
7. The web proxy starts after the API is ready.

## Durability

- document bytes are content-addressed and SHA-256 verified;
- controlled object storage requires governance retention, bucket versioning and object lock;
- audit writes commit with a transactional outbox and reconcile to an external monotonic HMAC anchor;
- PostgreSQL custom-format bytes stream directly from `pg_dump` into AES-256-GCM without a plaintext backup file; the fsynced v4 manifest contains ciphertext/plaintext hashes, sizes and key ID and is HMAC-authenticated;
- restore is checksum-verified, single-transactional and followed by schema/RLS verification.

## Delivery

GitLab uses rootless BuildKit, secret/dependency/IaC/container scanning, source and image SBOMs, migration/RLS integration, encrypted backup-to-new-database restore, deterministic packaging from `git archive HEAD`, and protected release dependencies.
