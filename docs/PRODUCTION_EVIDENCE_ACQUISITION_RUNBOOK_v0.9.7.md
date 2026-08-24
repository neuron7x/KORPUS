# KORPUS v0.9.7 — Production Evidence Acquisition Runbook

This runbook is fail-closed. Workflow existence is not evidence. Every accepted artifact must bind the exact release, source digest, deployed revision/environment and trusted signer where required.

## 1. Final local closure

1. Execute all 64 regression shards on the final source freeze; merge must account for the exact live collection with zero failures/errors and no unauthorized skips.
2. Execute all 349 mutants on the same source freeze; required result: 349 killed, 0 survived, 0 invalid, 0 errors/timeouts.
3. Regenerate all CURRENT reports, `SOURCE_MANIFEST.json`, `PACKAGE_BUILD.json`, current truth and canonical package.
4. Verify the unpacked package from a clean gitless directory.

## 2. Exact environment

Run the API verification inside the pinned `python:3.12.13-slim-bookworm` image from `apps/api/Dockerfile`. Admit only a receipt proving all locked components, exact versions, no unmanaged distributions and the required Python version.

## 3. Real PostgreSQL / RLS

Provide `KORPUS_POSTGRES_TEST_URL` for an isolated production-like PostgreSQL instance. Execute the PostgreSQL security suite, role-grant tests, repository refusals, tenancy threats and audit persistence. Include positive access controls and negative cross-tenant attempts. Static SQL inspection is insufficient.

## 4. Hosted scanners and SBOM

Execute current-commit dependency, secret, container/OS and SBOM validation using hosted tooling. Bind scanner outputs to the exact source/image digest and admit them only through the configured evidence manifest/attestation path.

## 5. Hosted build provenance and release signing

Build in a governed hosted builder. Admit the builder identity in `trusted-builders.v1.json` only after governance approval. Generate verifiable provenance for the exact artifact digest. Sign the final release only after every prior mandatory gate passes.

## 6. Production-like load / soak / recovery

Deploy an exact immutable candidate revision. Execute sustained load/soak against declared SLO thresholds, then a backup/restore/PITR recovery drill. Sign both result packages with admitted assurance keys. A local synthetic scale probe is not a substitute.

## 7. Real-domain PEC / TEVV

Preregister corpus, metrics, null controls, attack families, decision criteria and exclusion rules before execution. Run against the actual intended domain corpus. Human production judgments must be joined by exact revision/profile/phase/cohort/training receipt. Model self-judgment is inadmissible.

## 8. Independent assurance

An independent assessor must reproduce/inspect TEVV in a production-like environment and sign the result with a separately governed key. An independent red-team must use preregistered structured cases, required attack-family coverage, structured findings and closure evidence for all blocking findings.

## 9. Promotion rule

Production promotion is allowed only when all 14 production hard predicates are externally satisfied. Weighted readiness, test count, local green CI or self-attestation cannot compensate for one failed mandatory predicate.
