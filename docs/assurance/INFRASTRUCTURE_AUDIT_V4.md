# Infrastructure audit v4

## Closed defect classes

| Defect class | Failure mode | Implemented predicate |
|---|---|---|
| Service wiring | Compose services existed but API did not consume them | runtime URLs/secrets and dependency order are machine-validated |
| Schema startup | API could start before migrations | migration job must complete before API |
| Database isolation | RLS covered only part of corpus data | FORCE RLS covers documents, versions, spans and embeddings under a non-superuser role |
| Credential scope | API could share storage administrator credentials | dedicated MinIO identity is restricted to `objects/*` and cannot delete objects |
| Object durability | retention setting did not prove bucket capability | readiness checks versioning and object lock when retention is enabled |
| Audit ambiguity | external anchor failure could follow a committed transaction | durable outbox decouples business commit and anchor delivery |
| Audit truncation | a signed but reset/stale anchor could be accepted | readiness compares anchor to historical event and recoverable outbox gap |
| Readiness cost | readiness scanned the entire ledger | bounded head/outbox/history checks replace O(N) verification |
| Backup confidentiality | raw database dump could persist | direct `pg_dump` stdout → streaming AES-256-GCM; no plaintext backup path |
| Backup provenance | restore could use a changed manifest, wrong key or wrong artifact | HMAC-authenticated manifest v4 binds filename, sizes, hashes, cipher and mandatory key ID |
| CI privilege | Docker-in-Docker expanded runner privilege | rootless BuildKit OCI builds, no privileged mode |
| Supply-chain visibility | release lacked SBOM and image scan | Syft SBOM plus Trivy/Gitleaks/pip-audit gates |
| Release contamination | packaging used mutable working tree | package originates from committed `git archive HEAD` |
| Network blast radius | web shared external/egress connectivity | internal edge/backend networks; only API joins egress |
| Resource exhaustion | services had no explicit ceilings | memory, CPU, PID, file-descriptor, timeout and log limits |
| Host-header abuse | upstream accepted arbitrary Host | explicit trusted-host middleware and proxy preservation |
| Silent reconciler failure | background anchor errors disappeared | bounded error-class metric plus readiness backlog evidence |
| Local command drift | Make target referenced a nonexistent profile | support/start targets name real services and wait for health |
| Resource lifecycle | SQLite handles could survive application teardown | SQLite uses `NullPool`; full suite promotes unraisable resource warnings to failures |
| Evidence coverage | source digest omitted release-relevant committed files | digest covers the complete committed tree except generated evidence |

## Deliberately open evidence

Static/local verification cannot prove a live Docker engine, PostgreSQL/pgvector runner, real S3 governance enforcement, production OIDC, remote anchor availability, external telemetry backend, multi-node failure recovery, penetration resistance or state authorization. Those remain deployment gates, not mocked PASS results.
