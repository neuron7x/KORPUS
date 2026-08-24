# KORPUS v0.9.7 — Infrastructure Reference

## Local/Compose topology
Services: `api`, `web`, `worker`, `migrate`, `postgres`, `minio`, `minio-init`, `clamav`, `otel-collector`.

Networks: `frontend`, `backend`, `edge`, `egress`.  
Volumes: `postgres-data`, `minio-data`, `clamav-db`, `audit-anchor`.

Static infrastructure validation: **135 requirements / 0 failures**.

## Kubernetes
Base: **19 resources / PASS**.  
Production overlay: **19 resources / PASS**.  
This is static topology validation, not live-cluster evidence.

## GCP target
- Cloud Run web + API.
- Cloud Run ingestion worker pool.
- Migration job.
- Candidate/canary probe job.
- PostgreSQL verification job.
- Cloud SQL over private/VPC-connected runtime.
- Global HTTPS/load-balancing edge with explicit TLS policy.
- Monitoring, SLO, burn-rate alerts and notification channels.
- PITR/backup-recovery drill machinery.
- Hosted build/provenance admission.

Static GCP production contract: **72/72 PASS**.  
Static GCP SLO contract: **11/11 PASS**.

## Promotion sequence
`foundation → hosted build/provenance → migration → real PostgreSQL verification → candidate revision → shadow/canary → load/recovery evidence → HUMAN/TEVV admission → traffic promotion`.
