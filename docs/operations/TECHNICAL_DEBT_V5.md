# KORPUS v5 — residual debt contract

This document records work that cannot be converted into PASS by local code or synthetic tests.

## Frozen audit debt counts

- 79/99 findings remain non-closed in the frozen audit scope.
- 33 are `MITIGATED_LOCAL`: a material local control exists, but external/live acceptance remains.
- 31 are `EXTERNAL_DEBT`: they require independent people, systems, infrastructure or authorization.
- 15 are `OPEN_TECH_DEBT`: repository engineering work remains.
- remaining severity: P0 21, P1 48, P2 10.

Machine-readable registers: `docs/audit/closure/KORPUS_v5_REMAINING_DEBT.json` and `.csv`.

## Domain-invariant debt (2026-08-04)

Eighteen of the twenty-seven canonical invariants recorded in
`docs/audit/INVARIANT_DIFF_2026-08-03.md` are closed by code, each with a failing test
and a mutant in `scripts/run_mutation_tests.py`. One is met by a stronger mechanism and
deliberately not ported verbatim. One — `superseded-never-current` — stays open: the
canonical reading takes an order out of force the moment anyone uploads a draft
successor, which is a denial of service triggered by ordinary work. It needs a process
owner's decision, not more code. Register: `docs/audit/INVARIANT_CLOSURE_2026-08-04.md`.

Closure was demonstrated on SQLite in the test profile. The PostgreSQL branches of the
validity queries, `pg_stat_database` checksum counting and `PRAGMA`-equivalent
integrity probing carry no executable evidence in that run — same category as the live
PostgreSQL debt below.

## External acceptance debt

- formal production and restricted-data authorization with a named risk owner;
- signed corpus rights, classification, releasability and data-owner manifests;
- independent TEVV, application pentest, AI red-team and parser/container assessment;
- live PostgreSQL/pgvector, Kubernetes, OIDC, S3 Object Lock, KMS/HSM and remote-anchor evidence;
- production load, soak, chaos, rollback, PITR and measured RTO/RPO;
- human gold dataset, blinded holdout and inter-annotator agreement;
- GitLab protected-branch/tag policy and trusted-runner evidence;
- signed build provenance, artifact signing and immutable registry promotion;
- on-call, incident exercises, SLO/error-budget operation and capacity ownership.

## Open engineering debt

- decomposition of the large SQL repository and security configuration validator;
- corpus-scale table, number, unit and formula evaluation;
- embedding backfill/model-migration orchestration and drift monitoring;
- production SIEM export, retention and correlation integration;
- reviewer/admin web workflows and accessibility validation;
- live-serving OpenTelemetry health probe and durable telemetry backend;
- environment drift and cost/capacity governance against a real cluster;
- complete dependency/license inventory with legal review.

### Closed 2026-08-05

A register that still lists closed work is a register nobody can act on, so entries
leave this list only with the mechanism that keeps them closed.

- **hash-locked dependency artifacts** — both lock files carry sha256 for all 68
  artifacts and every install site passes `--require-hashes` (Makefile, two CI steps,
  the API Dockerfile). Two tests hold it: one that every pin carries a hash, one that
  every install enforces them, since pip ignores `--hash` lines without the flag.
- **broad exception handlers in critical paths** — reading all fourteen showed they
  already re-raise, degrade or record. What was missing was anything holding the next
  one to it. `test_exception_handling_discipline.py` refuses a handler that returns a
  value indistinguishable from success, a bare `except:`, or an empty body; probed
  against five swallow shapes.
- **executable retention/deletion/legal-hold scheduler and reconciliation** —
  `application/retention.py` computes a disposition per document (HELD, RETAINED,
  ELIGIBLE, AWAITING_DECISION, UNGOVERNED) and `scripts/plan_retention.py` writes the
  plan and reconciles it against storage. It deletes nothing and is not a timer: in a
  corpus that answers "which order was in force on date X", automatic deletion would
  be data loss driven by a config field. `AWAITING_DECISION` exists because keeping
  expired material quietly reports a clean posture over something nobody ruled on.
  Mutants M121–M123 cover legal hold outranking the timer, deletion without
  permission, and an ungoverned corpus being treated as governed.

The machine-readable source of truth is `docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json`.
