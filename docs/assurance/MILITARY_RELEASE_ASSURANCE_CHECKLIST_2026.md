# KORPUS — Military Release Assurance Checklist 2026

Status semantics are strict: `[x]` means current release-bound evidence exists; `[ ]` means it does not. A software PASS cannot substitute for external or operational evidence.

## A. Tested-system identity
- [x] Release identity is singular and source-bound.
- [x] Source manifest is cryptographically verifiable.
- [x] Harness, dataset, configuration and environment identities are explicit TEVV dimensions.
- [x] Material harness/configuration/source changes invalidate performance carry-forward.

## B. Inference epistemics
- [x] Access filtering occurs before retrieval.
- [x] Temporal authority is explicit and stale authority is a hard failure.
- [x] Retrieval is bounded and deterministic under fixed inputs/configuration.
- [x] Claims must bind to evidence/citations.
- [x] Unsupported claims and missed mandatory abstention are hard failures.
- [x] Citation presence is not treated as citation entailment/correctness.
- [x] Presentation adaptation cannot change claim/evidence identity.

## C. Evaluation validity
- [x] Hard failures are conjunctive gates; mean accuracy cannot compensate.
- [x] Confidence intervals are reported for rare safety failures.
- [x] Aggregate volume cannot hide an untested required cohort.
- [x] Case IDs must be unique; duplicate evidence fails closed.
- [x] Synthetic evaluation cannot authorize production.
- [x] Independent evaluation is a distinct admission predicate.
- [x] Operational-environment evidence is a distinct admission predicate.
- [ ] Current real-domain Ukrainian military TEVV >= 400 release-bound observations.
- [ ] Independent evaluator/adjudicator evidence for the exact release.
- [ ] Human-system evaluation with soldiers/instructors across required cohorts.

## D. Software verification
- [x] Current-truth verifier passes on the packaged SSOT baseline before this iteration.
- [x] Package-build identity verifier passes on the packaged SSOT baseline before this iteration.
- [x] Module complexity ratchet is enforced.
- [x] Inference-security suite exists and is release-gated.
- [x] Formal/state-space assurance exists.
- [x] Mutation catalogue exists and its anchors are statically checked.
- [ ] Full current backend regression campaign completed after this iteration.
- [ ] Full current mutation catalogue completed after this iteration.
- [ ] Full property/metamorphic/differential campaign completed after this iteration.

## E. Operational evidence
- [ ] Live PostgreSQL FORCE-RLS adversarial campaign on the exact release.
- [ ] Production-like concurrent load/soak evidence.
- [ ] Chaos/fault injection and recovery drill evidence.
- [ ] Offline signed-pack field test including revocation/rollback/freshness failure modes.
- [ ] Current vulnerability, secret and container scan evidence.
- [ ] Hosted reproducible build provenance and trusted release signature.

## Release rule
Production authorization is TRUE only if **all mandatory software, epistemic, human-system and operational predicates are simultaneously satisfied for the exact tested-system fingerprint**. UNKNOWN is not PASS. Historical evidence is not current evidence unless cryptographically admissible under the release policy.

## Methodological basis
The checklist operationalizes 2026-era evaluation principles used across frontier-model and high-assurance engineering: tested-system identity rather than model-only evaluation; separation of claim, harness, resource budget and validity; adversarial/negative controls; independent evaluation; confidence-aware rare-event measurement; human-systems integration; operational T&E; fail-closed release evidence; and falsification before promotion.
