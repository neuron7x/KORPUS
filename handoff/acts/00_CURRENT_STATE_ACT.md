# Act 00 — current canonical state

- Canonical release: `v6.18.1` ACT-015 supply-chain container-image evidence closure.
- Production authorization: `false` until fresh `v6.18.1` evidence completes all required production gates.
- Last complete source-bound baseline: `v6.17.0` — 1410 collected tests, 1407 PASS, 0 FAIL, 0 ERROR, 3 SKIP; statement coverage 8545/9314 (91.7436%); branch coverage 1823/2312 (78.8495%); full mutation catalogue 299/299 killed; real Chromium/CDP local browser campaign 5/5 PASS.
- `v6.18.1` binds API/Web container scan success into the signed supply-chain evidence domain, requires exact artifact-set equality, and rejects stale scanner markers from another commit. Application runtime semantics are unchanged.
- Browser evidence remains `LOCAL_BROWSER_POLICY_COMPATIBLE`: network navigation, same-origin deployment and real OIDC/session-cookie execution remain unproved.
- Environment/external gates remain fail-closed where exact Python 3.12.13, real PostgreSQL, scanners/container SBOM attestations, production-like reliability, admissible TEVV and independent external red-team evidence are absent.

Interpretation: `v6.18.1` is the canonical engineering candidate only after fresh regression, coverage, mutation, browser E2E and assurance bind to its immutable source identity. Prior PASS artifacts are historical baseline only.
