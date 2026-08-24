# KORPUS v0.6.1 — Production Blocker Closeout

- Release: `v0.6.1`
- Source digest: `4183b5e2a3b1c69ec88eafc62c901ed972c5615e0c7dc25383577e0f785f2900`
- Verdict: `PASS_WITH_EXTERNAL_BLOCKERS`
- Production authorized: `false`

## Executed delta

- **independent_external_redteam** — `EXTERNAL_REQUIRED`. Internal adversarial campaign already PASS over all 9 required families; external report template is source/release/preregistration-bound. Remaining: Independent execution + completed structured report + Ed25519 attestation + pre-admitted signer.
- **live_production_like_postgresql** — `EXTERNAL_REQUIRED`. Static grant contract PASS and production-like harness/test targets are fixed. Remaining: Real PostgreSQL runtime and adversarial suite.
- **ruff_mypy_current_runtime** — `RUNTIME_UNAVAILABLE`. Canonical versions pinned; gate executed and recorded non-start instead of false PASS; compileall separately PASS. Remaining: Ruff 0.15.22 and Mypy 2.3.0 must execute in the locked Python 3.12.13 environment.
- **vulnerability_secret_container_scanners** — `RUNTIME_UNAVAILABLE`. Security scan command executed; absences recorded as exit 127; 68/68 locked records hash-covered; source SBOM lock complete. Remaining: Pinned Gitleaks, pip-audit, Trivy, container SBOM/scan and trusted attestation.
- **exact_deployment_environment** — `DECLARED_NOT_ATTESTED`. Target images and lock hashes are exact; desired-state artifact observation IN_SYNC for 25 declared artifacts. Remaining: Execute inside target Python 3.12.13/image graph; current harness is Python 3.13.5 and mismatched.
- **trusted_hosted_builder_signing** — `CONFIGURED_NOT_TRUSTED`. Release workflow SHA-pinned, OIDC/attestation permissions declared, static workflow validator PASS; local Ed25519 signing mechanism tested separately. Remaining: Hosted execution + independently admitted trust root.
- **live_load_soak_attestation** — `LOCAL_EXECUTION_CLOSED_EXTERNAL_ATTESTATION_PENDING`. Fresh live local load/spike/soak executed: 420 requests total; source-bound; reliability execution/SLO predicates pass locally. Remaining: PRODUCTION_LIKE/PRODUCTION environment + trusted load/recovery attestations.
- **production_tevv** — `EXTERNAL_REQUIRED`. Production TEVV schema/profile is executable and source-bound template generated. Remaining: At least 200 real observations, interval width <=0.1, 20+ null controls, required attack families, production-like environment, trusted attestation.
- **distribution_wrapper_integrity** — `CLOSED_IN_FINAL_WRAPPER`. Canonical predecessor wrapper failed its own verifier: 914 failures (1 nested-manifest path-set mismatch + 913 digest-record schema mismatches). Final wrapper uses the canonical 'bytes' field and the verifier's DISTRIBUTION_MANIFEST basename exclusion. Remaining: None after final archive verifier PASS.

## Fail-closed boundary

The remaining predicates require a different execution authority/environment or tools unavailable in the current harness. No local surrogate is promoted to external evidence.
