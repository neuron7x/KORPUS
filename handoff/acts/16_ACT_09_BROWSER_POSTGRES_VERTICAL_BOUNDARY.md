# ACT-09 — Browser-to-PostgreSQL vertical boundary

- Issue ID: `KORPUS-ACT-09`.
- Value hypothesis: conference evidence becomes materially stronger when one clean-room test
  traverses Chromium, nginx, FastAPI, the non-owner application role, and live PostgreSQL RLS,
  then proves that an authorized public fixture reaches the rendered evidence surface.
- Linked findings: `INF-001`, `IAM-006`; neither finding is closed by this act.
- Trust boundaries: browser authority storage; nginx security headers; JWT request identity;
  API role versus migration owner; PostgreSQL FORCE RLS; evidence JSON versus runtime state.
- Allowed files: reusable composed-boundary runner, its Playwright test and report validator,
  focused mutation tests, this act, and ignored `var/web-act/` evidence.
- Forbidden files: production credentials/data, RLS weakening, application-role ownership or
  migration authority, OIDC/production claims, frozen source audit evidence.
- Killable invariants: migration runs under an ephemeral admin identity; FastAPI receives only
  the application-role URL; browser observes the exact authorized fixture through PostgreSQL;
  forged/anonymous tokens fail; browser stores no authority; report binds Git and image
  digests, database versions and actual Alembic head; SQLite remains explicitly non-RLS.
- Adversarial cases: forged bearer token; absent authority storage; missing PostgreSQL image,
  version or migration binding; incorrect evidence marker; dirty candidate worktree.
- Acceptance predicates: static and mutation checks pass; both SQLite smoke and PostgreSQL
  vertical modes run after commit; PostgreSQL report validates; cleanup leaves no containers,
  volume, database, token or credential-bearing artifact; independent verification remains.
- Rollback: revert the bounded ACT-09 commits; no migration or persistent-state impact.
- Migration impact: none; existing migrations are executed in a disposable tmpfs database.
- Evidence generated: `var/web-act/web-api-live-boundary.json` and JUnit only. Tokens,
  credentials, database files and fixture content outside the sanitized report are transient.
- Executed gates: SQLite and PostgreSQL modes each passed 1/1 live Chromium test; the
  PostgreSQL v2 report bound API, web and PostgreSQL image digests, PostgreSQL 17.10,
  pgvector 0.8.5 and Alembic head `0009_reviewer_credentials`. API suite, seven non-live
  browser tests, web build and report mutation tests passed.
- Unexecuted gates: GitLab pipeline and independent verifier.
- Residual uncertainty: JWT is not production OIDC; IAM-006 remains `CONFIRMED_OPEN`; a
  compromised application process can still broaden GUC claims through arbitrary SQL.
- Verdict: `PASS_WITH_CAVEATS`; independent post-change verification is required and
  `production_authorized=false`.
