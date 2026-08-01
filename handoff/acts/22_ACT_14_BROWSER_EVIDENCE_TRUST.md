# ACT-14 — Browser evidence trust and provenance

- Issue ID: KORPUS-ACT-14
- Value hypothesis: performance evidence is falsifiable only when the verifier, rather than the report producer, owns the budgets and the browser execution environment is identified.
- Audit finding IDs: conference evidence follow-up; no external finding is claimed closed.
- Trust boundary touched: Playwright report producer ↔ deterministic report validator ↔ independent verifier.
- Files/modules allowed: live browser test, its report validator and contract mutation tests, this act contract and verifier index.
- Files/modules forbidden: delivered application behavior, CSP, API/RLS policy, production authorization, frozen audit source.
- Killable invariants: report budgets exactly equal validator-owned constants; budget inflation is rejected; Chromium version/user agent/device scale factor and cold ephemeral context are explicit; missing or malformed browser provenance fails closed.
- Adversarial cases: inflated LCP budget, substituted browser engine, empty version, non-Chromium user agent, non-unit device scale factor, warm/persistent cache claim, missing provenance.
- Acceptance predicates: every adversarial receipt is rejected; valid schema-v4 receipt passes; normal and clean PostgreSQL live browser tests pass; final report SHA equals Git HEAD and remains non-authorizing.
- Migration/data impact: none.
- Rollback: revert the bounded ACT-14 commits; no state migration is required.
- Commands executed: web lint/static budget validation; 21 report-contract tests; normal Playwright suite (7 passed, live test environment-skipped); clean committed PostgreSQL live gate remains required.
- Evidence artifacts: `var/web-act/web-api-live-boundary.json` and JUnit only.
- Gates not executed: independent clean-room verifier, production browser population, production network and GitLab pipeline.
- Remaining uncertainty/debt: browser identification makes local evidence reproducible but does not turn one local observation into a population percentile or production SLO.

## Reproduced defect

Schema v3 accepted a report after increasing both a measured value and its report-local budget. Because producer-controlled thresholds cannot authorize their own result, performance budgets are moved into exact validator constants in schema v4.
