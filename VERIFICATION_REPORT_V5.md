# Verification report — KORPUS v5.0.0

> **HISTORICAL v5 SNAPSHOT — NOT CURRENT RELEASE EVIDENCE.** See `VERIFICATION_REPORT.md`.

Verification date: 2026-08-01.

## Executed local gates

| Gate | Procedure | Result | Evidence class |
|---|---|---|---|
| Functional/property/state/concurrency/security tests | branch-aware `pytest` suite | 172 collected; 171 PASS; 1 live-PostgreSQL SKIP; 0 failures/errors | ANCHORED_LOCAL |
| Coverage | XML від інструмента coverage (стороннього, не файла дерева) над ядром довіри API | line 87.00%; branch 66.87%; combined gate 82.60% | ANCHORED_LOCAL |
| Adversarial evaluation | frozen 30-case dataset and protocol | 30/30 PASS | ANCHORED_LOCAL |
| Citation binding | exact substring, offsets, quote/source hash | 17 checks; 0 failures | ANCHORED_LOCAL |
| Access noninterference | identity/corpus/tier/compartment isolation | 0 leakage failures | ANCHORED_LOCAL |
| Determinism | repeated semantic outputs | 0 failures | ANCHORED_LOCAL |
| Critical mutation testing | six isolated shards and completeness merge | 26/26 selected mutants killed | ANCHORED_LOCAL |
| Clean migration parity | Alembic empty-DB upgrade vs metadata | 9/9 expected tables; FTS5 present; PASS | ANCHORED_LOCAL |
| Bounded scale probe | SQLite FTS5, 5,000 spans, 80 queries, budget 256 | p50 2.315 ms; p95 2.783 ms; max 4.602 ms; top-1 1.0 | ANCHORED_LOCAL_MEASUREMENT |
| Operational composition | eval + mutation + migration + scale | PASS; `production_authorized=false` | ANCHORED_LOCAL |
| Web | validation, typecheck and static build | PASS | ANCHORED_LOCAL |
| Static deployment contracts | OpenAPI, repository, Compose, Kubernetes | PASS; Kubernetes 20 resources; Compose 9 services | ANCHORED_LOCAL_STATIC |
| Frozen audit classification | exact set comparison | 99/99 findings classified | ANCHORED_LOCAL |

## Material v5 controls added

1. Token privilege claims are projected through a server-side content-addressed entitlement registry.
2. Need-to-know compartments are enforced before retrieval in application policy and database RLS.
3. Browser authentication uses an opaque BFF session with PKCE/state/nonce/CSRF rather than persisted bearer tokens.
4. Uploads stream to quarantine and pass type verification, malware scanning and parser isolation before corpus admission.
5. Ingestion jobs have durable lease/retry/dead-letter semantics.
6. Source authenticity, near-duplicate state and extraction quality are first-class review evidence.
7. Reviewer authority is scoped, expiring, revocable and content-addressed; stage credentials are persisted and audited.
8. Corpus policy explicitly controls allowed operations, retention, legal hold and external model egress.
9. Calibration binds parameters to dataset, evaluation protocol, system manifest and model configuration hashes.
10. Claims are exact cited substrings and contradiction checks can force abstention.
11. Kubernetes reference topology uses restricted pod settings and default-deny network policy.
12. The complete v4 assurance act is retained and every one of its 99 findings has a v5 status.

## Audit closure

- `CLOSED_LOCAL`: 20 — ANCHORED by closure register count.
- `MITIGATED_LOCAL`: 33 — ANCHORED by closure register count.
- `EXTERNAL_DEBT`: 31 — ANCHORED by closure register count.
- `OPEN_TECH_DEBT`: 15 — ANCHORED by closure register count.
- Remaining non-closed severity: P0 21, P1 48, P2 10 — ANCHORED by closure register.

`CLOSED_LOCAL` does not mean production-safe. It means only that the frozen local acceptance predicate has executable evidence.

## Not executed or not provable locally

- live PostgreSQL/pgvector RLS, concurrency and backup→restore;
- live Docker or Kubernetes deployment;
- production OIDC, S3 Object Lock, KMS/HSM, embedding, audit-anchor and telemetry services;
- Ruff and mypy execution in this environment; they remain mandatory fail-closed CI jobs;
- complete hash-locked dependency artifacts, license clearance and signed build provenance;
- independent application/cloud pentest, AI/RAG red-team and parser/container assessment;
- real-corpus OCR/retrieval/attribution/abstention TEVV with human adjudication;
- load, soak, chaos, failover, PITR and measured RTO/RPO;
- corpus rights, classification, official reviewer appointments and formal production authorization.

## Verdict

- Engineering baseline: `PASS_WITH_CAVEATS`.
- Controlled pilot on open/synthetic data: `PASS_WITH_CAVEATS`.
- Ordinary production: `FAIL` until external/live gates close.
- Restricted military production: `FAIL` until authorization and all applicable P0/P1 evidence close.
