# ACT-16 — PostgreSQL evidence fail closure

- Issue ID: `KORPUS-ACT-16`.
- Value hypothesis: a live database receipt is useful only when its independent validator rejects security regressions represented inside otherwise well-formed JSON.
- Linked findings: `INF-001`, `INF-005`, `IAM-006`; no external finding is closed.
- Trust boundaries: PostgreSQL catalogs and live probes → assurance producer → JSON validator → independent verifier.
- Allowed files: PostgreSQL assurance producer/validator, focused evidence tests, mutation harness, this contract and verifier index.
- Forbidden files: frozen audit source, migrations, runtime authorization policy, production configuration and `production_authorized` state.
- Killable invariants: exact single Alembic head; five-table missing-context zeros; public/restricted and compartment isolation; enabled and forced RLS with SELECT policy on every governed table; reviewed grant vocabulary and read-only migration state; non-skipped live JUnit; equal 64-hex state digests; internally consistent IAM-006 result; complete relevant mutation receipt.
- Adversarial cases: missing governed table, leaked public identity, disabled FORCE RLS, forged Alembic UPDATE grant, skipped live test, malformed/equal placeholder digest, contradictory IAM status/count, invalid or surviving mutant.
- Acceptance predicates: every adversarial payload is rejected; stale pre-ACT-16 evidence is rejected; 29/29 mutation targets are killed; clean live PostgreSQL/backup/restore evidence generated after commit passes and binds final HEAD; `production_authorized=false`.
- Migration/data impact: none; all databases, credentials and keys remain ephemeral.
- Rollback: revert the bounded ACT-16 commit and regenerate evidence with the preceding validator; no database rollback is required.
- Commands executed: focused Ruff; 33 focused assurance/Alembic/backup tests; full six-shard mutation gate; final live and repository gates recorded after commit.
- Evidence generated: ignored ACT-01 JSON/JUnit/log/manifest plus `var/mutation-report.json`; no key, ciphertext, plaintext dump or credential-bearing URL is retained.
- Unexecuted gates: GitLab pipeline and independent clean-room verification.
- Residual uncertainty: IAM-006 remains `CONFIRMED_OPEN`; local successful validation is not independent acceptance or production authorization.
