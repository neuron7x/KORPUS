# KORPUS v0.9.4 — End-of-Day Session Closure — 2026-08-21

- Snapshot role: **END_OF_DAY_CANONICAL_SESSION_SNAPSHOT**
- Production authorization: **FALSE**
- Source digest: `a7637ee25bb70e45aa94febeab601803e6a7111a1420dc177191f0c1fe34f584`
- Current truth: **PASS**
- Full readiness: **PASS**
- Regression: **258/258 test modules; 33/33 batches PASS**
- Mutation: **312/312 KILLED**, survivors=0, invalid=0, errors=0, score=1.0
- Inventory: **221 source modules; 258 test_* modules; 1786 static tests**

## Integrated hardening

- Central external-destination/SSRF policy refuses loopback, private, link-local, unspecified and IPv6 ULA literal destinations.
- Controlled audit-anchor transport requires external HTTPS.
- Browser OIDC cookie-prefix policy enforces host-bound session/CSRF cookies, secure flow cookie, distinct names and production secret checks.
- Secure cookie deletion semantics are enforced for logout/callback paths.
- Logout has route-level double-submit CSRF enforcement even when SameSite suppresses the session cookie.
- HSTS and nginx add_header inheritance are validated across deployment edges.
- ZIP admission enforces entry-count, total-uncompressed, per-entry and compression-ratio ceilings.
- ZIP resource admission occurs before structural traversal and safe extraction validates before filesystem writes.
- Package/mutation sandbox import portability was repaired.
- Architecture ratchet remained bounded without increasing legacy module ceilings; hardening was decomposed into dedicated security primitives.
- Mutation catalogue expanded from 305 to 312 with direct falsifiers for new hardening invariants.
- A direct causal CSRF middleware falsifier was added after the M21 evidence-drift survivor.

## External production boundary

Software-side contracts ready: **12/12**. Externally satisfied: **0/12**. Production-satisfied: **0/12**.

- `external_independent_redteam` — `EXTERNAL_INDEPENDENT_ATTESTED`
- `live_vulnerability_scanners` — `CURRENT_SCANNERS_PLUS_SBOM_ATTESTED`
- `live_postgres_rls` — `REAL_POSTGRESQL`
- `real_domain_corpus_tevv` — `REAL_DOMAIN_CORPUS`
- `independent_tevv` — `INDEPENDENT_ATTESTED`
- `production_like_tevv_environment` — `PRODUCTION_LIKE_OR_PRODUCTION_ATTESTED`
- `production_like_load` — `PRODUCTION_LIKE_LOAD`
- `trusted_load_attestation` — `TRUSTED_LOAD_ATTESTATION`
- `trusted_recovery_attestation` — `TRUSTED_RECOVERY_ATTESTATION`
- `trusted_hosted_builder` — `HOSTED_BUILDER_PROVENANCE`
- `trusted_release_signing` — `PRETRUSTED_RELEASE_SIGNER`
- `exact_python_3_12_13_environment` — `EXACT_LOCKED_ENVIRONMENT`

## Continuation invariant

Do not carry PASS across changed executable source bytes. External independence/trust predicates must not be self-attested by the same agent that produced the software.
