# Verification report — KORPUS v4.0.0

Verification date: 2026-08-01.

## Executed local gates

| Gate | Procedure | Result |
|---|---|---|
| Functional/property/state/concurrency/infrastructure tests | `pytest apps/api/tests` | 125 collected; 124 PASS; 1 live-PostgreSQL SKIP; 0 failures/errors/warnings |
| Coverage threshold | branch-aware coverage.py | combined 82.34%; statements 86.72%; branches 64.78% |
| Adversarial evaluation | `scripts/run_evals.py` | 30/30 PASS |
| Citation binding | exact substring, offsets, quote/source hash | 19 checks; 0 failures |
| Access noninterference | identity/corpus/tier isolation | 0 leakage failures |
| Determinism | repeated semantic outputs | 0 failures |
| Critical mutation testing | 3 isolated shards + completeness merge | 14/14 killed; 0 survived/invalid |
| Clean migration parity | Alembic empty-DB upgrade vs SQLAlchemy metadata | PASS |
| SQLite search index | migrated FTS5 objects | PASS |
| Local bounded scale probe | 5,000 spans, 80 queries, budget 256 | p50 2.017 ms; p95 2.981 ms; max 9.302 ms; top-1 1.0 |
| Operational composition | eval + mutation + migration + scale | PASS; `production_authorized=false` |
| Backup crypto | AES-256-GCM round trip and ciphertext tamper | PASS |
| Backup/restore shell contract | foreign CWD, stream backup, key binding, manifest tamper | PASS |
| Resource lifecycle | full suite with unraisable DB-handle warnings promoted to error | PASS |
| Web | install, validation, typecheck, static build | PASS |
| Repository/infrastructure | static contract, compileall, YAML parse, `git diff --check` | PASS |

## Infrastructure defects removed

1. Compose support services existed without complete runtime wiring.
2. API could start before migrations and application-role preparation.
3. RLS protected only part of the corpus graph.
4. API object storage could depend on administrative credentials.
5. Object-lock configuration was declared without readiness verification.
6. Remote anchor failure could make a committed operation appear failed.
7. Readiness performed unnecessarily expensive ledger verification.
8. Audit truncation/reset states were not fully distinguished from recoverable backlog.
9. Docker build did not consume the exact runtime lock contract.
10. GitLab used an unnecessarily privileged image-build model and lacked complete scan/SBOM gates.
11. Web bypassed the same-origin proxy path and shared excess network reachability.
12. Services lacked explicit resource, PID, log and filesystem restrictions.
13. Positive readiness exposed excess infrastructure detail.
14. Controlled configuration could be bypassed by an unknown environment string.
15. Controlled PostgreSQL did not require server identity verification.
16. PostgreSQL CI could test under a superuser and thereby bypass RLS semantics.
17. Application-role grants were broader than required.
18. Backup and restore depended on the caller working directory.
19. Restore used a pre-created temporary file that the fail-closed decryptor correctly refused to overwrite.
20. Backup first materialized a plaintext database dump on disk.
21. Backup manifest metadata was not cryptographically authenticated.
22. Restore key-ID validation was optional.
23. Restore did not compare actual plaintext byte count to the manifest.
24. SQLite pooling could retain DB-API handles across application lifecycles.
25. Release packaging could use mutable working-tree state.
26. Assurance source digest covered only a selected subset of the committed tree.
27. CI packaging attempted to snapshot evidence before assembling source-bound assurance.
28. Coverage reporting conflated combined coverage with statement coverage.

## Provenance classification

- Test, coverage, evaluation, mutation and migration results: **ANCHORED** to generated local artifacts.
- Scale result: **ANCHORED_LOCAL_MEASUREMENT** on synthetic SQLite FTS5 data; not a production SLA.
- Docker, PostgreSQL/pgvector service execution, real S3 retention, OIDC, remote anchor and external telemetry behavior: **UNKNOWN locally**.
- State/military authorization, corpus authority and production safety: **NOT ESTABLISHED**.

## Not executed locally

- Docker/Compose runtime: Docker executable unavailable.
- Live PostgreSQL/pgvector integration and actual database restore: no PostgreSQL service available; encoded as mandatory GitLab gates.
- Ruff and mypy: required GitLab jobs; local packages unavailable.
- Production OIDC, embedding, S3/object-lock, remote-anchor and telemetry endpoints.
- Independent penetration test, malware/CDR validation, real-corpus OCR benchmark, rights/classification review and formal authorization.

This report proves only the listed executable predicates against the supplied source, fixtures and local environment.
