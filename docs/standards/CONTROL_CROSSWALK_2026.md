# KORPUS control crosswalk — 2026

This is a **traceability map**, not a compliance certificate. External standards define broad concerns; KORPUS closes them only through its own executable invariants, source-bound reports and independent evidence where required.

| KORPUS control family | Internal mechanism | External concern aligned | Evidence expectation |
|---|---|---|---|
| Source integrity | source manifest, exact release identity, reproducible package | NIST SSDF provenance/release discipline; SLSA source/build integrity | byte-identical source binding + artifact digest |
| Authorization before retrieval | policy engine, corpus/compartment scopes, tenancy isolation | OWASP ASVS access-control verification | negative-control tests for cross-tenant/cross-compartment leakage |
| Untrusted corpus handling | instruction/data separation, source authenticity, parser/scanner policy | OWASP ASVS input/file handling; NIST AI RMF risk measurement | adversarial corpus vectors + ingestion tests |
| Supported-answer boundary | citation alignment, evidence coverage, abstention | NIST AI RMF Measure/Manage concerns | claim/evidence tests and reference eval |
| Secure development | quality gate, mutation, module ratchet, deterministic CI | NIST SSDF | source-bound quality + test + mutation evidence |
| Supply chain | locks, SBOM, package verification, no Git-history distribution | SLSA provenance / NIST C-SCRM themes | complete dependency inventory + scanner evidence |
| Operational safety | admission control, recovery, audit anchor, migration rollback | NIST SSDF operational feedback; AI RMF Manage | production-like load/recovery evidence |
| Independent assurance | external red-team evidence class, trusted attestation | assurance independence principle | independently signed release-bound evidence |

## Interpretation rule

A row cannot be marked “closed” merely because a control exists in source. Closure requires evidence with an evidence class sufficient for the release stage. Static configuration can support a design review; production authorization requires executed and, for selected gates, independently attested evidence.
