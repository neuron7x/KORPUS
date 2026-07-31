# KORPUS v3.0.0 distribution contents

This distribution is a GitLab-ready operational-reference baseline for a controlled evidence platform.

Included executable components:

- FastAPI modular monolith with versioned contracts and server-derived identity;
- SQLite FTS5 and PostgreSQL GIN/`tsvector` bounded lexical candidates;
- pgvector semantic candidates with deterministic bounded fusion;
- explicit convex ranking utility, BM25 parameters, MMR, per-version cap and deadlines;
- reproducible weight tuning with nDCG, MRR, Recall and finite-sample risk gates;
- risk-adaptive abstention and explicit dependency-outage decisions;
- application ABAC plus PostgreSQL `FORCE ROW LEVEL SECURITY`;
- immutable canonical documents, temporal versions, spans and content-addressed objects;
- PDF embedded-text extraction, bounded OCR fallback and hostile-input limits;
- quarantine, separated review roles, approval and optimistic-concurrency transitions;
- exact extractive claims with offsets, quote hashes and source hashes;
- OIDC/JWKS, S3, embedding, pgvector, OpenTelemetry, Prometheus and remote-anchor adapters;
- identity/release/config-bound cache, admission control and circuit breakers;
- persistent hash-chained audit, CAS head, remote HMAC checkpoint and transactional outbox;
- offline-capable dependency-free PWA;
- 108-test verification lattice: properties, state machines, races, temporal semantics and noninterference;
- 30-case adversarial evaluation and 14-mutant critical mutation gate in three shards;
- Alembic migration parity, indexed scale probe and PostgreSQL service-container gate;
- GitLab CI, CODEOWNERS, MR controls, dependency/secret scans, SBOM and container builds;
- isolated Codex/Claude worktree protocol, runbooks, machine-readable assurance and deterministic manifest.

Not included because they require external authority or deployment-specific evidence:

- the claimed 5,960-file real corpus and authoritative metadata;
- document rights, classification decisions and appointed domain reviewers;
- production identity provider, embedding service, HSM/KMS, S3 object lock and remote anchor;
- queue-backed automatic embedding reconciliation for corpus changes;
- independent penetration-test and real-corpus OCR reports;
- formal security profile, authorization/accreditation and operational SOC ownership;
- validated production latency, concurrency, recovery, cost and availability SLA.
