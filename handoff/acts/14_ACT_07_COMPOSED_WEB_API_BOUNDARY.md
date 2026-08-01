# ACT-07 — Composed browser, nginx and API boundary

- Issue ID: `KORPUS-ACT-07`.
- Value hypothesis: browser confidence materially increases when the production web/API images are booted together and tested without intercepting API traffic.
- Trust boundaries: Chromium ↔ nginx; `/api/v1` rewrite ↔ FastAPI `/v1`; bearer memory ↔ browser storage; API hardening headers ↔ edge headers; build-context modes ↔ non-root image runtime.
- Allowed files: web/API container boundary, Playwright configuration/test, reusable gate runner/validator, this act, transient `var/web-act/` evidence.
- Forbidden files: production credentials, OIDC simulation claims, PostgreSQL RLS claims from SQLite, production authorization, retained JWTs or persistent test volumes.
- Killable invariants: API and web images start as their fixed non-root users; anonymous identity is 401; ephemeral JWT identity is 200; answer transport is 200; forged token is 401; request correlation and hardening headers survive nginx; authority is absent from cookies/local/session storage; unknown assets are 404 while HTML navigations retain SPA fallback; evidence binds both image digests and the clean candidate commit.
- Reproduced failures: API image could not import `korpus.main` because `COPY` preserved source modes `0770/0660` and only parent directories were normalized; nginx returned `index.html` with 200 for `/favicon.ico`; edge/API headers were duplicated; the first live test did not open the intentional developer disclosure.
- Causal repairs: recursively normalize copied API runtime files to read/execute-only; restrict nginx SPA fallback to clients accepting HTML; canonicalize overlapping proxy headers; explicitly exercise the disclosure; preserve anonymous denial as a required case.
- Acceptance predicates: reusable self-cleaning runner passes from a clean commit; live Playwright test is 1/1; machine report and JUnit are emitted without JWT; standard browser/API/repository regressions remain green; independent verification remains required.
- Rollback: revert the bounded ACT-07 commit and rebuild both images. No migration or durable data impact; the runner deletes its named containers, network, volume and images.
- Migration impact: none.
- Evidence generated: `var/web-act/web-api-live-boundary.json`, `var/web-act/live-boundary-junit.xml`, failure screenshots only, and sanitized container/build logs. No token or test database is retained.
- Residual uncertainty: SQLite is not PostgreSQL/RLS evidence; ephemeral JWT is not production OIDC evidence; local Docker networking is not the production ingress/TLS topology.
- Verdict: `PASS_WITH_CAVEATS` after post-commit reproduction; `production_authorized=false`.
