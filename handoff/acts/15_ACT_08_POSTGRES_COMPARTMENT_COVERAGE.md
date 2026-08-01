# ACT-08 — PostgreSQL compartment relation coverage

- Issue ID: `KORPUS-ACT-08`.
- Value hypothesis: compartment noninterference is incomplete unless the join relation itself is tested, because leaking document identifiers or compartment names remains disclosure even when document text is hidden.
- Linked findings: `INF-001`, `IAM-006`; no finding is closed by this act.
- Trust boundaries: application role ↔ `document_compartments` FORCE RLS; missing context ↔ relation metadata; exact/unrelated compartment ↔ document-to-compartment mapping.
- Allowed files: focused live PostgreSQL integration and backup tests, backup producer,
  infrastructure validator, this act, transient ACT-01/ACT-08 evidence.
- Forbidden files: RLS policy weakening, role privilege expansion, production data/credentials, production authorization.
- Killable invariants: public identity sees no restricted compartment row; missing identity sees zero compartment rows; missing or unrelated compartment cannot see the protected document or mapping; exact compartment sees exactly the intended `(document_id, compartment)` row.
- Adversarial cases: direct SQL against the join relation; unrelated compartment; exact compartment; absent authorization context.
- Acceptance predicates: targeted changed-code checks pass; the PostgreSQL test executes live
  rather than skips; no plaintext dump file is created; strengthened backup/restore evidence
  validator passes; broader regressions remain green; independent verification remains required.
- Rollback: revert the bounded ACT-08 commit. No migration or persistent-state impact; live databases are disposable.
- Migration impact: none.
- Pre-fix evidence: real PostgreSQL 17 `pg_dump --file=-` created a 52,801-byte plaintext
  file literally named `-`; the encryption stream received zero bytes and manifest creation
  failed on `plaintext_bytes`. The artifact and ephemeral key were deleted after measurement.
- Causal repair: omit `--file` so PostgreSQL's documented default stdout stream feeds
  authenticated encryption; the test double now models real file-option semantics, and the
  infrastructure validator rejects reintroduction of `--file=-`.
- Second pre-fix failure: the PostgreSQL gate image completed restore but could not emit
  evidence because it has no `git` executable. Candidate provenance now consumes an explicit
  full `KORPUS_CANDIDATE_COMMIT`/`CI_COMMIT_SHA`, validates its shape, and only uses local Git
  as a fallback; GitLab exports the pipeline commit explicitly.
- Diff-attack correction: DB-11 now emits and validates positive anchored backup, restore,
  verification, and arithmetically consistent total-recovery durations.
- Commands executed: focused backup/restore pytest; 14 evidence and mutation tests;
  infrastructure validator; targeted Ruff; shell syntax and diff checks; clean PostgreSQL
  17.10/pgvector 0.8.5 migration, live RLS pytest, encrypted backup, restore into a new
  database, post-restore verifier, evidence generator and deterministic validator.
- Final live observations: current head `0009_reviewer_credentials` on source and restore;
  application role has all five prohibited role flags false; missing-context counts are zero
  for all five governed corpus relations; compartment cases are missing=0, unrelated=0,
  exact=1; source and restore digest are identical; JUnit reports one live test and no skips;
  measured backup=0.425923s, restore=0.944987s, verification=0.513206s,
  total=1.884116s. Measurements are local `ANCHORED`, not a production SLA.
- Evidence generated: transient JUnit, sanitized live-assurance JSON, and authenticated
  backup manifest only. Ciphertext, plaintext and encryption keys are not retained.
- Residual uncertainty: IAM-006 remains `CONFIRMED_OPEN`; this test does not prevent a compromised application process from setting broader GUC claims.
- Unexecuted gates: independent post-change verification, GitLab pipeline, and relevant
  mutation shard. Local script mypy was unavailable because the existing environment lacks
  `pathspec.patterns.gitignore`.
- Verdict: `PASS_WITH_CAVEATS`; independent verification remains required and
  `production_authorized=false`.
