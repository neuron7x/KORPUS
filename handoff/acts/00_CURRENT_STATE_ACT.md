# Act 00 — current canonical state

- Canonical release: `v6.16.0` ACT-013 structured TEVV observation/null ledgers with recomputed production metrics.
- Production authorization: `false` until fresh `v6.16.0` evidence completes all required production gates.
- Last complete source-bound baseline: `v6.15.0` — 1395 collected tests, 1392 PASS, 0 FAIL, 0 ERROR, 3 SKIP; statement coverage 8495/9255 (91.7882%); branch coverage 1809/2294 (78.8579%); full mutation catalogue 291/291 killed.
- `v6.16.0` invalidates all `v6.15.0` PASS artifacts as current-release evidence. They remain historical baseline only.
- ACT-013 changes the TEVV evidence class: trusted aggregate counters are insufficient; observations, null controls, attack-family coverage and failure counts are recomputed from structured case ledgers under schema `korpus.tevv-evidence.v2`.
- Production-assurance CLI relative-path provenance handling is also hardened and mutation-tested.
- Environment/external gates remain fail-closed where exact Python 3.12.13, real PostgreSQL, scanners/container SBOM attestations, production-like reliability, admissible TEVV and independent external red-team evidence are absent.

Interpretation: `v6.16.0` is an engineering continuation point until fresh regression, coverage, mutation and assurance are regenerated against its immutable source digest. No prior release artifact is admissible as current evidence.
