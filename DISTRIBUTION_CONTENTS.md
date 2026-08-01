# KORPUS v4.0.0 distribution contents

GitLab-ready infrastructure-hardened baseline for a controlled evidence platform.

## Included executable components

- FastAPI modular monolith with server-derived identity and versioned contracts;
- application ABAC plus PostgreSQL `FORCE ROW LEVEL SECURITY` across every corpus table;
- SQLite FTS5 and PostgreSQL GIN/`tsvector` bounded lexical retrieval;
- optional pgvector semantic candidates gated by real calibration evidence;
- deterministic ranking, risk-adaptive abstention, MMR and bounded candidate/deadline budgets;
- immutable documents, temporal versions, evidence spans and content-addressed objects;
- PDF/TXT/JSON/HTML ingestion, bounded OCR fallback and hostile-input limits;
- separated review roles, optimistic concurrency and single-current-version enforcement;
- exact extractive claims with offsets, quote hashes and source hashes;
- cached/rotation-safe OIDC/JWKS verification;
- S3-compatible SHA-256-verified storage with controlled object-lock checks;
- persistent hash-chained audit, CAS head, remote HMAC checkpoint and transactional outbox;
- bounded readiness and low-cardinality Prometheus/OpenTelemetry instrumentation;
- direct `pg_dump`→AES-256-GCM backup streaming with authenticated manifest v4;
- fail-closed restore with key-ID, HMAC, hash, byte-count and migration verification;
- non-root, read-only, resource-bounded Compose services on separated edge/backend/egress networks;
- rootless BuildKit OCI builds, Gitleaks, pip-audit, Trivy and Syft gates;
- PostgreSQL downgrade/upgrade, non-superuser RLS and encrypted backup→new-database CI drill;
- deterministic package from `git archive HEAD` with source-digest-bound assurance evidence;
- dependency-free offline-capable PWA;
- Codex/Claude isolated worktree protocol and operational runbooks.

## Release evidence

- 125 tests collected: 124 PASS, 1 live-PostgreSQL SKIP, 0 failures;
- combined coverage 82.34%; statement coverage 86.72%; branch coverage 64.78%;
- adversarial evaluation 30/30 PASS;
- critical mutation gate 14/14 killed;
- migration/schema parity PASS;
- local scale probe PASS;
- operational composition gate PASS with `production_authorized=false`;
- web and static infrastructure validation PASS.

## Deliberately not included or not proven locally

- the claimed 5,960-file real corpus and authoritative metadata;
- document rights, classification decisions and appointed domain reviewers;
- production OIDC, embedding, HSM/KMS, external S3/object lock, remote audit-anchor and telemetry services;
- live Docker/Compose execution in the generation environment;
- live PostgreSQL/pgvector and actual backup restore in the generation environment;
- registry digest promotion for deployment images;
- hash-pinned Python wheels;
- independent penetration test, real-corpus OCR benchmark and malware/CDR assessment;
- formal security profile, authorization/accreditation, SOC ownership or production SLA.
