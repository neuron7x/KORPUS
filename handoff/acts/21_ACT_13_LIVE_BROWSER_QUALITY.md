# ACT-13 — Live browser quality evidence

- Issue ID: KORPUS-ACT-13
- Value hypothesis: conference evidence is stronger when accessibility, responsive layout, and bounded browser performance are measured on the real nginx/API/PostgreSQL path rather than inferred from mocked browser tests.
- Audit finding IDs: conference vertical-slice assurance follow-up; no external finding is claimed closed.
- Trust boundary touched: Chromium ↔ nginx ↔ FastAPI ↔ application-role PostgreSQL, and machine-report consumer ↔ browser measurements.
- Files/modules allowed: live Playwright boundary test, live evidence validator/contract tests, reusable live runner, this task contract and verifier evidence index.
- Files/modules forbidden: production authorization, frozen audit source, API/RLS policy, corpus data, external analytics or runtime dependencies.
- Killable invariants: zero serious/critical automated accessibility violations; no horizontal overflow at 390 CSS pixels; no external browser origin; bounded navigation, LCP, CLS, answer latency and transferred shell bytes; evidence validator rejects absent, non-finite, or over-budget measurements.
- Adversarial cases: forged zero accessibility result, negative/NaN metric, metric over budget, external origin, missing measurement basis, production authorization.
- Acceptance predicates: contract mutation matrix rejects every malformed receipt; normal browser suite passes; clean live PostgreSQL browser gate emits schema v3 evidence bound to final commit and image digests; evidence remains `PASS_WITH_CAVEATS` and `production_authorized=false`.
- Migration/data impact: none; only ephemeral public test evidence is inserted into a disposable PostgreSQL database.
- Rollback: revert the bounded ACT-13 commit; no data rollback is required.
- Commands executed: web lint/static budget validation; 17 evidence-contract tests; normal Playwright suite (7 passed, live test environment-skipped); clean committed PostgreSQL live gate remains required.
- Evidence artifacts: `var/web-act/web-api-live-boundary.json` and live JUnit; token and database state remain transient.
- Gates not executed: manual assistive-technology review, production network measurements, independent clean-room verification and GitLab pipeline.
- Remaining uncertainty/debt: axe is a bounded automated oracle; local timings are anchored observations, not production SLOs or complete WCAG/Core Web Vitals certification.

## Reproduced failure

The first committed live run timed out at `page.goto(..., {waitUntil: "networkidle"})` despite a healthy service-worker application. Network idleness is not a stable readiness predicate for this topology. The repair restores the deterministic document `load` boundary and relies on explicit UI/API assertions before collecting measurements.

The next live run proved that nginx CSP correctly blocks post-load inline `axe` injection. CSP remains unchanged; axe is installed through Playwright's pre-navigation init script, keeping the oracle outside the delivered runtime and avoiding an unsafe CSP exception.

## Verified local result

- Clean Chromium → nginx → FastAPI → application-role PostgreSQL gate: PASS (`1/1`).
- Evidence schema: `korpus.web-api-live-boundary.v3`; validator: PASS.
- Automated accessibility: serious `0`, critical `0`.
- Responsive layout at 390 CSS pixels: content width `390`, horizontal overflow `0`.
- Anchored local observations: navigation `395.1 ms`, LCP `222.4 ms`, CLS `0`, answer `187 ms`, same-origin transfer `20,287 bytes`, external origins `0`.
- These observations are not a production SLO, comparative benchmark, or complete accessibility certification.
