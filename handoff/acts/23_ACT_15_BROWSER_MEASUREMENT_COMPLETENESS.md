# ACT-15 — Browser measurement completeness

- Issue ID: KORPUS-ACT-15
- Value hypothesis: conference performance evidence must fail closed when a named metric is unavailable rather than relabeling a different lifecycle timestamp as that metric.
- Audit finding IDs: conference evidence follow-up; no external finding is claimed closed.
- Trust boundary touched: Chromium Performance API ↔ Playwright producer ↔ schema validator.
- Files/modules allowed: live browser producer, report validator/contract tests, verifier index and this contract.
- Files/modules forbidden: delivered runtime, CSP, API/RLS policy, production authorization and frozen audit source.
- Killable invariants: LCP must be an observed largest-contentful-paint entry; navigation/answer/transfer values must be positive; CLS may be zero but never negative/non-finite; content width must be positive and no wider than viewport; actual installed Playwright version is bound and validator-owned.
- Adversarial cases: absent LCP, zero navigation/answer/transfer, negative CLS, contradictory content width, missing/substituted Playwright version.
- Acceptance predicates: contract matrix rejects every adversarial receipt; browser suite passes; clean live PostgreSQL browser gate emits schema v5 bound to committed HEAD; `production_authorized=false`.
- Migration/data impact: none.
- Rollback: revert bounded ACT-15 commits; no state rollback is required.
- Commands executed: web lint/static budget validation; 27 report-contract tests; normal Playwright suite (7 passed, live test environment-skipped); clean committed PostgreSQL live gate remains required.
- Evidence artifacts: schema-v5 `var/web-act/web-api-live-boundary.json` and live JUnit.
- Gates not executed: independent verification, GitLab pipeline, manual assistive technology and production performance measurement.
- Remaining uncertainty/debt: LCP/CLS are anchored single-run observations, not field percentiles or production SLOs.

## Reproduced defect

Schema v4 used `navigation.domContentLoadedEventEnd` when no LCP entry existed, then serialized the fallback as `lcp_ms`. It also accepted zero-valued navigation, answer and transfer measurements and did not cross-check reported content width against the viewport.

The first committed schema-v5 live run failed because Chromium returned no LCP through `performance.getEntriesByType`. The repair uses the specified pre-navigation buffered `PerformanceObserver`; no lifecycle-timestamp fallback is restored.
