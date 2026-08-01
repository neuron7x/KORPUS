# ACT-06 — API rejection-path observability

- Issue ID: `KORPUS-ACT-06`.
- Value hypothesis: security rejection is trustworthy only when denied requests receive the same correlation, no-store/hardening headers, timing, and HTTP observation path as accepted requests.
- Trust boundaries: invalid browser session/CSRF input ↔ API middleware; early denial ↔ response hardening; rejected request ↔ telemetry.
- Allowed files: API middleware, focused browser-auth tests, this act, transient test evidence.
- Forbidden files: authorization weakening, CSRF bypass, production telemetry destinations, secrets, production authorization.
- Killable invariants: invalid session remains 401; missing/mismatched CSRF remains 403; every rejection has a valid request ID, `nosniff`, `no-referrer`, and `no-store`; supplied valid request IDs are preserved; every rejection calls the HTTP observer with its actual status and nonnegative duration.
- Adversarial cases: malformed sealed session; session present without CSRF; caller-supplied correlation ID; denial before router dispatch.
- Acceptance predicates: focused browser-OIDC suite passes; API suite and repository validators remain green; changed files pass Ruff/compile; independent verification remains required.
- Rollback: revert the bounded ACT-06 commit. No migration or persistent-state impact.
- Migration impact: none.
- Evidence generated: transient pytest output/JUnit only; no session cookie value is retained.
- Residual uncertainty: local observation proves middleware invocation, not delivery to a production OTLP collector or production incident response.
- Verdict: `PASS_WITH_CAVEATS` after local tests; production remains unauthorized.
