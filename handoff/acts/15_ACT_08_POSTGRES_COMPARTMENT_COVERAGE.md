# ACT-08 — PostgreSQL compartment relation coverage

- Issue ID: `KORPUS-ACT-08`.
- Value hypothesis: compartment noninterference is incomplete unless the join relation itself is tested, because leaking document identifiers or compartment names remains disclosure even when document text is hidden.
- Linked findings: `INF-001`, `IAM-006`; no finding is closed by this act.
- Trust boundaries: application role ↔ `document_compartments` FORCE RLS; missing context ↔ relation metadata; exact/unrelated compartment ↔ document-to-compartment mapping.
- Allowed files: focused live PostgreSQL integration test, this act, transient ACT-01 evidence.
- Forbidden files: RLS policy weakening, role privilege expansion, production data/credentials, production authorization.
- Killable invariants: public identity sees no restricted compartment row; missing identity sees zero compartment rows; missing or unrelated compartment cannot see the protected document or mapping; exact compartment sees exactly the intended `(document_id, compartment)` row.
- Adversarial cases: direct SQL against the join relation; unrelated compartment; exact compartment; absent authorization context.
- Acceptance predicates: targeted Ruff passes; the PostgreSQL test executes live rather than skips; strengthened backup/restore evidence validator passes; broader regressions remain green; independent verification remains required.
- Rollback: revert the bounded ACT-08 commit. No migration or persistent-state impact; live databases are disposable.
- Migration impact: none.
- Evidence generated: transient JUnit and sanitized live-assurance JSON only.
- Residual uncertainty: IAM-006 remains `CONFIRMED_OPEN`; this test does not prevent a compromised application process from setting broader GUC claims.
- Verdict: `PASS_WITH_CAVEATS` only after post-commit live execution; `production_authorized=false`.
