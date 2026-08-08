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

## Commands, with the output that means "good"

Every check below is a command, its expected output, and the threshold. A runbook step
that is a sentence is a step nobody can execute under pressure.

| question | command | good |
|---|---|---|
| Is the API up? | `curl -sf localhost:8000/health` | `{"status":"ok"}` |
| Is it ready to serve? | `curl -sf localhost:8000/ready` | `200`, `{"status":"ready",…}` |
| Is the audit chain intact? | `make audit-verify` | `valid: true` |
| Do the release gates pass? | `make operational-gate` | `"status": "PASS"` |
| What is proven vs external? | `cat docs/operations/CURRENT_STATUS.md` | 9 external, 5 grounds |
| Bring the private stack up | `make infra-up` | web + worker `--wait` healthy |
| Bring it down | `make infra-down` | all services removed |

A red `operational-gate` names the failing predicate; a red `audit-verify` names the first
invalid sequence. Neither is a judgement call — read the field it prints.
