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
- corpus-scale table and formula evaluation;
- embedding backfill and model-migration execution against a real index;
- reviewer/admin web workflows and accessibility validation;
- live-serving OpenTelemetry health probe and durable telemetry backend;
- environment drift and cost/capacity governance against a real cluster;
- legal review of the declared dependency licenses.

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
- **SIEM export** — `application/audit_export.py` builds resumable, gap-evident
  batches and `scripts/export_audit.py` writes JSON Lines with a manifest and a
  cursor. It refuses to ship a batch whose sequences jump or whose hash links do not
  join: a collector cannot detect a missing event by itself, so a gap shipped quietly
  becomes a clean audit trail over a hole. Payloads stay behind by default — they
  quote corpus material and a SIEM is routinely a lower-classification system — and
  the digest travels instead. The manifest states what an HMAC link does *not* prove:
  a collector cannot detect rewriting by whoever holds the key; that remains the
  external anchor's job. Mutants M124–M126. Correlation into a specific SIEM product
  remains external, like every other integration with a system nobody here operates.
- **dependency license inventory** — read from installed distribution metadata:
  68 of 68 components now carry a declared license where all 68 read UNKNOWN. Legal
  review stays open and is listed above, because a publisher's declaration is not
  clearance for this delivery. The generator exits non-zero when a pinned package is
  absent from the environment, since running it under a bare interpreter resolved five
  of sixty-eight and reported the rest as unknown — a number describing the invocation
  rather than the supply chain. A parity test keeps it on the locked interpreter.
- **number and unit evaluation** — `application/numeric_integrity.py`. Every existing
  extraction predicate fires on visibly broken text; the failure that changes what an
  order *says* leaves the text clean. "не менше 300 м" read as "не менше 3 00 м" has a
  fine alphanumeric ratio, no replacement characters and no long tokens: quotable,
  citable, and wrong by two orders of magnitude. Five forms are detected — a number
  split by a space, a Cyrillic letter standing in for a digit, two decimal separators
  in one passage, a unit pushed past a line break, an inverted range — and each is
  paired with an ordinary passage that must *not* fire, because a flag a reviewer sees
  everywhere is a flag nobody reads. They join `extraction_quality_flags`, which
  already blocks a review transition until acknowledged, so the detection changes a
  decision rather than filling a field. Mutants M127–M128. Table and formula structure
  remain open above.
- **embedding drift monitoring** — `application/embedding_coverage.py`. Retrieval
  filters vectors by the active model id, so a model change yields no semantic
  candidates rather than wrong ones, and the lexical half answers alone from a
  narrower set than the calibrated profile assumed. Four states are distinguished
  because the operator's next move differs: COMPLETE, BACKFILL_REQUIRED,
  MODEL_MIGRATION_REQUIRED and STALE_VECTORS — stale ranked above missing, since
  missing produces silence and stale produces confidence about text the document no
  longer contains. An empty corpus reports 0.0 coverage, not 1.0. Required-semantic
  mode refuses an incomplete index instead of degrading. Mutants M129–M131.

The machine-readable source of truth is `docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json`.
