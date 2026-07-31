# Verification report — KORPUS v2.0.0

Verification date: 2026-07-31.

## Executed gates

| Gate | Procedure | Result |
|---|---|---|
| Functional/property/state tests | `pytest apps/api/tests` | 68 collected; 67 PASS; 1 PostgreSQL-only SKIP |
| Line coverage | Cobertura from branch-aware pytest | 88.88% |
| Branch coverage | Cobertura from branch-aware pytest | 66.67% |
| Frozen assurance evaluation | `scripts/run_evals.py` | 30/30 PASS |
| Citation binding | exact substring, offsets, quote/source hash | 19 checks; 0 failures |
| Access noninterference | public identity vs restricted corpus/markers | 0 leakage failures |
| Determinism | repeated semantic outputs | 0 failures |
| Critical mutation testing | `scripts/run_mutation_tests.py` | 11/11 mutants killed |
| Review/version state machine | illegal transitions, optimistic races, supersession | PASS |
| Audit integrity | mutation, truncation, concurrency, CAS head, HMAC anchor | PASS |
| Transaction outbox recovery | failed external anchor then reconciliation | PASS |
| Migration parity | clean Alembic upgrade vs SQLAlchemy metadata | PASS |
| Search-index migration | SQLite FTS5 created from empty database | PASS |
| Bounded retrieval | candidate generation cannot call full-corpus path | PASS |
| Local scale probe | 5,000 synthetic spans; 80 queries; candidate budget 256 | PASS; local measurement only |
| Web lint/typecheck/build | dependency-free validation and static PWA build | PASS |
| Repository/syntax | repository contract, `compileall`, `git diff --check` | PASS |

## Local scale measurement

Latest release snapshot records the exact values and environment in `reports/SCALE_REPORT.json`. This is an `ANCHORED_LOCAL_MEASUREMENT`, not a production SLA. PostgreSQL network, concurrent load, real corpus morphology and disk behavior remain unmeasured locally.

## Not executed in this container

- PostgreSQL service-container test: encoded in GitLab CI, locally skipped because no PostgreSQL service was available.
- Ruff and mypy: jobs and strict configuration exist, but the local package registry did not expose the tools; result remains `UNKNOWN` until a connected runner executes them.
- Docker image/Compose runtime: Docker executable unavailable.
- Independent penetration test, malware/CDR validation, real-corpus OCR benchmark, rights/classification review and formal authorization/accreditation: external evidence obligations.

This report proves only the listed procedures against synthetic/reference fixtures. It does not claim operational authorization for restricted military data.
