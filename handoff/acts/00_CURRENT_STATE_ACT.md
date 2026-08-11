# Act 00 — current canonical state

- Canonical release: `v6.17.0` ACT-014 real Chromium/CDP product-surface verification with explicit evidence boundaries.
- Production authorization: `false` until fresh `v6.17.0` evidence completes all required production gates.
- Last complete source-bound baseline: `v6.16.0` — 1409 collected tests, 1406 PASS, 0 FAIL, 0 ERROR, 3 SKIP; statement coverage 8545/9314 (91.7436%); branch coverage 1823/2312 (78.8495%); full mutation catalogue 299/299 killed.
- `v6.17.0` invalidates all `v6.16.0` PASS artifacts as current-release evidence. They remain historical baseline only.
- ACT-014 adds a real Chromium/CDP browser campaign for authenticated consumer boot under a deterministic transport fixture, answer/citation XSS escaping, typed 429 behavior, 390 px mobile overflow and admin/reviewer preview gating.
- Browser evidence is explicitly `LOCAL_BROWSER_POLICY_COMPATIBLE`: network navigation, same-origin deployment and real OIDC/session-cookie execution remain unproved and must not be inferred from the local browser PASS.
- Environment/external gates remain fail-closed where exact Python 3.12.13, real PostgreSQL, scanners/container SBOM attestations, production-like reliability, admissible TEVV and independent external red-team evidence are absent.

Interpretation: `v6.17.0` is an engineering continuation point until fresh regression, coverage, mutation, browser E2E and assurance are regenerated against its immutable source identity. No prior release artifact is admissible as current evidence.
