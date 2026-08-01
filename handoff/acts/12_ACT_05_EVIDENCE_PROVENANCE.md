# ACT-05 — PostgreSQL evidence provenance

- Issue ID: `KORPUS-ACT-05`.
- Value hypothesis: live database assurance is reviewable only when every successful machine claim is derived from an observed database predicate or authenticated artifact, never from a generator constant.
- Linked findings: `INF-001`, `INF-005`, `IAM-006`; this act changes evidence integrity, not finding closure.
- Trust boundaries: CI command result ↔ JUnit receipt; encrypted backup ↔ authenticated manifest; application role ↔ migration state; observed predicates ↔ aggregate verdict.
- Allowed files: PostgreSQL assurance generator/validator, focused tests, GitLab job wiring, this act, transient `var/act-05/` evidence.
- Forbidden files: frozen audit source, production data, keys, backup payloads, database files, production authorization, RLS policy weakening.
- Killable invariants: zero executed tests cannot report PASS; failing/error JUnit cannot report PASS; ciphertext checksum/length/HMAC/key-id mismatch cannot report verified; application-role Alembic UPDATE must be observed denied; any failed prerequisite forces report verdict FAIL; a non-FAIL report with a violated prerequisite is rejected by the independent deterministic validator.
- Adversarial cases: tampered encrypted bytes; wrong or absent JUnit; empty test suite; forged `manifest_verified=true`; mismatched source/restore digest; `rolbypassrls=true`; missing expected revision; credential-bearing URL.
- Acceptance predicates: unit mutation matrix passes; changed Python files pass Ruff and compilation; CI exports exact backup/JUnit artifact paths; a clean live PostgreSQL/backup/restore execution produces a validator-accepted report; `production_authorized=false`; independent verification remains required.
- Rollback: revert the bounded ACT-05 commit. No database migration or persistent-state change is introduced.
- Migration impact: none.
- Evidence generated: transient JUnit, authenticated backup manifest, and `var/act-01/postgres-live-assurance.json`; no key, ciphertext, plaintext dump, credential URL, or database volume is committed.
- Unexecuted gates: live post-change PostgreSQL/backup/restore and GitLab pipeline remain explicit until executed against this candidate.
- Residual uncertainty: a CI receipt proves the bounded commands and artifacts, not production operations, disaster-recovery SLA, or independence of the application-controlled IAM-006 context.
- Verdict: `PASS_WITH_CAVEATS` only after live execution; otherwise `FAIL`/unavailable.
