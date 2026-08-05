# KORPUS v5 — residual debt contract

This document records work that cannot be converted into PASS by local code or synthetic tests.

## Frozen audit debt counts (reclassified 2026-08-05)

- 75/99 findings remain non-closed in the frozen audit scope.
- 40 are `MITIGATED_LOCAL`: a material local control exists, but external/live acceptance remains.
- 31 are `EXTERNAL_DEBT`: they require independent people, systems, infrastructure or authorization.
- 4 are `OPEN_TECH_DEBT`: repository engineering work remains.

The counts above were stale for a day. `build_audit_closure.py` classifies by a static
set, so nine findings closed or mitigated on 2026-08-05 still read as open engineering
debt while the register reported on them — a document about closure that had not closed
its own loop. Every move carries the test that fails without the fix and, where the
finding is about code, the mutant that removes it and dies. Three moved to
`CLOSED_LOCAL` (SUP-002 hashed locks, COD-002 validator complexity, COD-003 broad
handlers) and six to `MITIGATED_LOCAL`, where the residue is external or partial and
is named below rather than counted as finished:

| finding | closed here | what remains |
|---|---|---|
| RAG-013 | numbers, units, table structure | formula structure |
| RAG-017 | embedding drift, four states | online answer-quality monitoring |
| INF-009 | telemetry reports REQUESTED_NOT_ACTIVE | a durable telemetry backend |
| SUP-009 | 68/68 licenses from metadata | legal review |
| COD-004 | branch coverage 0.7726, gated where produced | the 0.13 gap to line coverage |
| AUD-004 | resumable, gap-evident export | the SIEM that receives it |

SUP-001 closed later the same day: every image in the pipeline, the compose file and
both Dockerfiles is pinned by digest with its tag kept beside it for readability. The
concrete cost of tags had shown up hours earlier, when a kaniko version that does not
exist reached a queued pipeline — a digest cannot be invented, and cannot be repointed
at different bytes afterwards.

RAG-009 followed: the risk classifier is a register of rules carrying ids, rationales
and their own examples, and an unmatched query is UNCLASSIFIED rather than STANDARD.
Two defects sat behind that finding and only one was about regular expressions. The
second was direction: an unrecognised query fell to the loosest evidence thresholds in
the system, which is fail-open in the one place this design is otherwise fail-closed.
UNCLASSIFIED is now scored at the temporal setting — stricter than ordinary, not so
strict that operators learn to ignore refusals. What stays open is the acceptance
predicate the audit actually states: a trained classifier on a blind set with per-class
precision, recall and worst-group metrics, which needs annotated queries nobody here
has. That is `MITIGATED_LOCAL`, not closed.

COD-001 moved partly: the audit read side — verification, event lookup, readiness — is
now `infrastructure/audit_reader.py`, and `SqlRepository` is 1643 lines rather than
1855. That is the seam the class actually has. Most of the rest cannot be split without
splitting a transaction: `create_version_bundle` writes rows and their audit event
atomically, and an abstraction separating them would break that atomicity or leak it.
Cutting somewhere the class does not part would be the same debt in more files, so the
finding stays open with its measurement recorded rather than closed by rearrangement.

The extraction cost six mutants their targets and they went INVALID — the documented
behaviour, and the reason it is a gate. It also exposed a defect one level up: the
failed mutation run left its previous report in place, so the operational gate read
evidence from a tree that no longer existed and reported "generated from a different
source tree" — accurate, and three steps from the cause. A failed run now removes its
report: absent evidence and stale evidence must not be the same state.

Still `OPEN_TECH_DEBT`: RAG-016 (embedding model migration executed against a real
index), COD-001 (the transactional core of SqlRepository), WEB-001 (reviewer
workflows), OPS-004 (environment drift against a real cluster).

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

- decomposition of the SQL repository (1855 lines, worst function complexity 23);
- the repository and kubernetes validators still hold their checks inline;
- formula evaluation, and table structure recovered from PDF layout rather than flagged;
- embedding backfill and model-migration execution against a real index;
- reviewer/admin web workflows, and contrast/focus-order validation against a rendered page;
- a durable telemetry backend and its retention;
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
- **live telemetry health probe** — `Observability.telemetry_status()` distinguishes
  DISABLED from REQUESTED_NOT_ACTIVE. The exporter is attached only while the global
  tracer provider is still the proxy, so a configured `otlp_endpoint` can be ignored,
  and until now nothing told an operator reading that config that no span reaches the
  collector. Reported, not enforced: the release policy allows telemetry display to
  degrade while the underlying event stays durably available, and the audit chain is
  not the tracer. `/ready` carries the status word only — it is unauthenticated, and
  the collector address is internal.
- **accessibility validation** — `apps/web/scripts/validate.mjs` now asserts the
  properties a keyboard or screen-reader user depends on: exactly one h1, no skipped
  heading level, an accessible name on every button, a bound label on every control,
  alt on every image, a skip link, a main landmark, and a live region on the panel that
  script fills after an answer arrives. Seven negative controls, one per rule. The web
  shell failed four of them when the rules were first run — the interface had been
  fully verified for what it must not leak and not at all for whether it could be
  operated. Contrast and focus order need a rendered page and stay open above.
- **security configuration validator** — the thirty conditions a controlled deployment
  must satisfy moved out of `Settings.validate_security_and_calibration` into
  `korpus/controlled_requirements.py` as a declared list. Measured complexity of that
  method fell from 103 to 57.

  The number is not the benefit. The benefit is that the conditions are now a document
  that reads start to finish — for an engineer, for the §2.5 assessor, for whoever
  signs the authorisation — instead of control flow to be traced, and the list sits at
  the same granularity as the tests that weaken it one entry at a time. Order is
  preserved exactly, because a configuration violating several conditions reports the
  first, and the 43 tests pinning those messages were written before the move: they
  passed unchanged, which is what makes the refactor evidence rather than hope.

  Growth is now ratcheted. `scripts/check_module_budget.py` records today's line count
  and worst-function complexity for all 94 modules; shrinking is free, growth fails,
  and a new module without a recorded ceiling fails too — "not yet budgeted" is how a
  file reaches two thousand lines unnoticed. Three negative controls. Decomposing the
  repository itself stays open above, with its measurement written down.
- **infrastructure validator, and one register for every requirement** —
  `validate_infrastructure.main` held about a hundred checks inline and measured a
  cyclomatic complexity of 102. It is now 5: the checks live in
  `korpus/infrastructure_requirements.py` as data, and `application/requirements.py`
  applies them.

  The number was the symptom. Three things were missing and none of them is about
  complexity. A failure had no name — only the sentence appended where it happened —
  so it could not be cited in an audit, marked accepted-with-risk by an owner, matched
  to a mutant, or counted. A mutant could not reach one check among a hundred in one
  function, leaving ninety-nine individually unfalsified. And the requirements could
  not be read: §2.5 asks an outside assessor to judge this system, and the first thing
  they need is the list of properties it claims, not a program that emits that list
  while running.

  157 requirements now carry ids, positive statements and their reasons, exported to
  `REQUIREMENTS_REGISTER.md` and regenerated in `validate`, so a requirement added
  without regenerating fails the gate instead of leaving the document one behind.
  Behaviour is unchanged and the messages are preserved: `test_infrastructure_
  hardening.py` passed untouched, which is what makes a refactor of a security
  validator evidence rather than hope. Mutants M143–M145; M145 survived its first
  probe, because asserting "the register has no duplicate ids" is satisfied by a
  detector that always returns none.
- **table evaluation** — `application/table_integrity.py`. Norms live in tables, and
  PDF extraction has no notion of a cell. The failure is not that a flattened table
  looks broken: a row that loses a column shifts its figures left, so a value is quoted
  under another column's heading. The passage stays grammatical, the citation resolves
  to real bytes, and the answer states a norm that does not exist. Neither the
  character predicates nor `numeric_integrity` can see it — a correct number in the
  wrong column is a correct number.

  Blocks of table-like rows that disagree about their own column count are flagged, and
  the flag joins the same review gate. The first version of the module had the
  membership rule backwards: a row needed three columns to belong to a block, so the row
  that *lost* one broke the block instead of making it ragged, and every damaged table
  read as clean. Nine paired tests — each damage case beside an ordinary passage that
  must not fire — plus mutants M132–M134. Recovering the original cell structure, as
  opposed to detecting its loss, needs layout-aware extraction and stays open above.

The machine-readable source of truth is `docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json`.
