# Verification report

Verification date: 2026-07-31.

## Executed gates

| Gate | Procedure | Result |
|---|---|---|
| API functional tests | `pytest apps/api/tests` | 28/28 PASS |
| Python coverage | `pytest --cov ... --cov-fail-under=85` | 87.98% PASS |
| Frozen evaluation | `scripts/run_evals.py` | 5/5 PASS |
| Access leakage | public identity vs restricted marker/corpus | PASS |
| Prompt-injection null | instruction-like query without evidence | abstention PASS |
| Version supersession | approved v2 excludes approved v1 | PASS |
| Audit tampering | mutate first ledger event | detection PASS |
| Local bootstrap | ingest + three review transitions | PASS |
| Audit verification | verify bootstrapped ledger | 4 events, valid PASS |
| Web validation | zero-dependency asset contract | PASS |
| Web build | static PWA build | PASS |
| Database migration | Alembic `0001_initial -> head` on SQLite | PASS |
| Python syntax | `compileall` | PASS |
| Repository contract | `scripts/validate_repository.py` | PASS after final generation |

## Not executed in this container

- Docker image/Compose runtime: Docker executable unavailable.
- Ruff and mypy: package registry available to this container did not expose the pinned tools. GitLab jobs are defined, but their result remains UNKNOWN until a connected runner executes them.
- Independent penetration test, malware/CDR test, PostgreSQL load test and formal authorization: external gates, not inferable from repository tests.

This report proves the listed procedures only. It does not claim production accreditation or validate the real corpus.
