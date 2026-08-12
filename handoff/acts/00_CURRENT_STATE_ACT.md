# Act 00 — current canonical state

- Canonical release: `v6.18.2` ACT-016 verification-path closure.
- Production authorization: `false` until fresh `v6.18.2` evidence completes every required production gate.
- Last complete source-bound baseline: `v6.18.1` — 1415 collected tests, 1414 PASS, 0 FAIL, 0 ERROR, 1 SKIP; statement coverage 91.753351%; branch coverage 78.849481%; full mutation catalogue 302/302 killed; web unit 127/127 PASS; Chromium browser campaign 5/5 PASS.
- `v6.18.2` makes the OpenAPI drift gate executable under the same restricted `PYTHONPATH` used by Make/CI and removes a test-only dependency on injecting the scripts directory as a top-level module namespace. Application runtime semantics are unchanged.
- Fresh targeted verification for the changed path is PASS; the full 1416-test campaign was collected successfully but did not complete inside the current execution substrate, so historical v6.18.1 PASS evidence is not promoted to v6.18.2.
- External/production-only gates remain fail-closed where exact Python 3.12.13, real PostgreSQL, scanner/container-SBOM attestations, production-like reliability, admissible TEVV and independent external red-team evidence are absent.

Interpretation: `v6.18.2` is the canonical engineering candidate. It becomes a production release only when fresh source-bound evidence for this exact tag clears the 12-gate profile and the protected release pipeline signs the assurance and artifact.
