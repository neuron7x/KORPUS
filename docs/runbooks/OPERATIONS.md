# Operations — v4

## Daily evidence

- query `/ready` through the authenticated operations path;
- compare database audit head, remote anchor head, outbox gap and oldest pending age;
- inspect anchor reconciliation failures, ingestion denials, authorization denials and admission saturation;
- verify PostgreSQL, object-lock/versioning and telemetry dependency health;
- check backup replication and the latest completed restore drill, not only backup job completion.

## Release sequence

1. Merge only a protected, reviewed commit with every required GitLab job green.
2. Build OCI artifacts rootlessly from committed source.
3. Scan source, dependencies, IaC and built images; generate source/image SBOMs.
4. Run clean migration, downgrade/upgrade, non-superuser RLS and encrypted backup→new-database restore.
5. Assemble assurance from JUnit, coverage, adversarial, mutation, migration, scale and operational reports.
6. Verify the assurance source digest against committed `HEAD`.
7. Package from `git archive HEAD`; copy only explicitly generated, content-hashed evidence.
8. Promote immutable registry digests, not mutable tags, in the deployment environment.
9. Record image digest, migration revision, calibration profile and corpus release identifier.
10. Stop rollout on evidence, access, audit, readiness, restore or dependency regression.

## Failure domains

- `edge`: web proxy only; no direct backend or egress access.
- `backend`: API, PostgreSQL, object storage and collector; internal network only.
- `egress`: API only; OIDC, embeddings and remote anchor.
- Database commit and external audit-anchor delivery are separated by a durable outbox.
- Object storage, PostgreSQL backups and audit anchors are independent durability domains.

## Backup invariant

A backup is valid only after an authenticated manifest, successful decryption, exact hash/size agreement, transactional restore, expected Alembic revision, non-superuser RLS isolation and valid audit head are demonstrated.
