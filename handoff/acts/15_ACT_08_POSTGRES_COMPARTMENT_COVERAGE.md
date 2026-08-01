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
- Commands executed: focused backup/restore pytest; infrastructure validator; shell syntax
  check; diff check. The first post-commit live chain failed closed at manifest validation and
  is retained in the task transcript; a clean rerun is required after commit.
- Evidence generated: transient JUnit, sanitized live-assurance JSON, and authenticated
  backup manifest only. Ciphertext, plaintext and encryption keys are not retained.
- Residual uncertainty: IAM-006 remains `CONFIRMED_OPEN`; this test does not prevent a compromised application process from setting broader GUC claims.
- Verdict: `PASS_WITH_CAVEATS` only after post-commit live execution; `production_authorized=false`.
