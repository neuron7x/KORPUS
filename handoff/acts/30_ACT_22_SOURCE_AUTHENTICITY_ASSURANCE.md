# ACT-22 — Exemplary source-authenticity boundary

- Value hypothesis: corpus integrity requires deterministic, exhaustive fail-closed verification of detached source signatures.
- Linked findings: `RAG-018`, `DATA-003`, `SUP-003`; this local act closes none of them.
- Trust boundary: untrusted trust-profile bytes and document metadata → Ed25519 verification → ingestion eligibility.
- Allowed files: source-authenticity module/tests, focused mutation/evidence, this act and verifier index.
- Forbidden files: production keys, real restricted data, authorization/RLS policy, frozen audit source and production authorization.
- Killable invariants: same signed inputs never depend on wall time; bounded keys require a signed date; every metadata field is signature-bound; malformed, unknown, revoked, wrong-issuer, wrong-authority and out-of-window inputs fail closed.
- Adversarial cases: invalid Base64, wrong key length, map/key mismatch, digest substitution, missing signature half, metadata mutation and both validity edges.
- Acceptance: 100% statement and branch coverage for the selected module, critical mutants killed, full regression/eval/determinism green.
- Rollback: revert the bounded ACT-22 commit; no migration or data rollback.
- Migration impact: none.
- Residual uncertainty: local synthetic Ed25519 keys do not establish external issuer governance, revocation distribution, HSM custody or production PKI authorization.

## Demonstrated result

- Pre-fix defect: a bounded key used `date.today()` when signed metadata had no publication/effective date, so identical inputs could change verdict across calendar time.
- Repair: bounded keys require an explicitly signed reference date; unbounded keys read no wall clock.
- Focused proof: 10 tests pass; `71/71` statements and `26/26` branches covered (`100%`).
- CI consequence: `api:source-authenticity` enforces `--cov-branch --cov-fail-under=100` and retains JSON/JUnit evidence.
- Mutation consequence: `M31_BOUNDED_SOURCE_KEY_WITHOUT_SIGNED_DATE` restores the bypass and must be killed.
