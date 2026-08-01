# ACT-10 — PostgreSQL privilege falsification

- Issue ID: `KORPUS-ACT-10`.
- Value hypothesis: a role is not least-privileged merely because five role flags are false;
  verifier-ready evidence must actively fail privileged statements and prove non-ownership.
- Linked findings: `INF-001`, `IAM-006`; neither finding is closed by this act.
- Trust boundaries: application role versus governed table owners, public schema, database,
  migration state, policies, roles and extensions.
- Allowed files: reusable PostgreSQL assurance probe, live PostgreSQL integration test,
  evidence validator and mutation tests, this act, ignored transient evidence.
- Forbidden files: grants or ownership expansion, RLS weakening, production credentials/data,
  frozen audit source, production authorization.
- Killable invariants: schema/database CREATE are false; governed-table ownership count is
  zero; CREATE/ALTER/DROP table, CREATE POLICY/SCHEMA/EXTENSION/ROLE, ALTER ROLE and SET ROLE
  each fail independently; Alembic UPDATE remains denied; no missing probe can validate.
- Adversarial cases: each privileged statement executes in a fresh transaction so one failed
  transaction cannot manufacture later PASS results; validator requires the exact probe set.
- Acceptance predicates: targeted static and mutation tests pass; old evidence is rejected;
  clean live PostgreSQL test executes without skip; new evidence contains every PASS receipt;
  repository regressions remain green; independent verification remains required.
- Rollback: revert the bounded ACT-10 commit. No migration or persistent-state impact.
- Migration impact: none.
- Evidence generated: refreshed sanitized ACT-01 JSON/JUnit only; no database, key, password,
  token or connection URL is retained.
- Executed gates: clean PostgreSQL source/restore cycle passed; application-role schema and
  database CREATE were false, governed-table ownership count was zero, and all ten exact
  denial identifiers passed. API suite, repository/infrastructure/Kubernetes validators,
  migration gate and 30/30 deterministic eval cases passed.
- Unexecuted gates: external mutation tool shard, GitLab pipeline and independent verifier.
- Residual uncertainty: these probes do not mitigate IAM-006; arbitrary application-role SQL
  can still broaden values in the current GUC authorization context.
- Verdict: `PASS_WITH_CAVEATS`; independent post-change verification is required and
  `production_authorized=false`.
