# Act 00 — current canonical state

- Canonical release: `v6.17.1` ACT-014.1 browser-evidence closure consistency patch.
- Production authorization: `false` until fresh `v6.17.1` evidence completes all required production gates.
- Last complete source-bound baseline: `v6.17.0` — 1410 collected tests, 1407 PASS, 0 FAIL, 0 ERROR, 3 SKIP; statement coverage 8545/9314 (91.7436%); branch coverage 1823/2312 (78.8495%); full mutation catalogue 299/299 killed; real Chromium/CDP local browser campaign 5/5 PASS.
- `v6.17.1` regenerates the machine-readable audit closure so WEB-001 evidence resolves to the Chromium runner and package entrypoint already present in ACT-014. No application-runtime feature is added by this patch.
- Browser evidence remains `LOCAL_BROWSER_POLICY_COMPATIBLE`: network navigation, same-origin deployment and real OIDC/session-cookie execution remain unproved.
- Environment/external gates remain fail-closed where exact Python 3.12.13, real PostgreSQL, scanners/container SBOM attestations, production-like reliability, admissible TEVV and independent external red-team evidence are absent.

Interpretation: `v6.17.1` is the canonical engineering candidate only after fresh regression, coverage, mutation, browser E2E and assurance bind to its immutable source identity. Prior PASS artifacts are historical baseline only.
