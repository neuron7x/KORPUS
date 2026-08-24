# KORPUS v0.8.1 — Engineering Readiness 94.7 Protocol

## 1. Decision object

The 94.7 target is a preregistered engineering/technical/academic/theoretical maturity threshold. It is **not** a probability of correctness, a security certification, or production authorization. Production authorization remains a separate conjunctive decision under `config/assurance/production-v1.json`.

## 2. Evidence identity

An evidence observation is admissible for fusion only when it refers to the same claim, the same canonical source-tree digest, and the same release identity. Cross-source or cross-release evidence is not averaged, voted, or silently promoted.

## 3. Compatibility and conflicts

Compatible observations may be combined. Contradictory outcomes or values are preserved in an explicit conflict object. A material conflict makes the fused claim fail closed until the contradiction is resolved by new source-bound evidence. Conflict suppression is prohibited.

## 4. Evidence hierarchy

The evaluator applies the canonical assurance evidence ceilings implemented in `korpus.application.assurance_calculus`: declaration < static inspection < executed evidence < executed evidence with negative controls < independent attested evidence. Missing criteria score zero. Source/release mismatch zeros the affected dimension.

## 5. Inference budget

The canonical inference budget is `config/assurance/inference-budget.v1.json`:

- maximum cycles: 8;
- maximum evidence items: 512;
- maximum explicit conflicts: 64.

A reasoning cycle stops at an epistemic fixpoint when the decision fingerprint is unchanged and no new admissible evidence was added. It also stops immediately when any hard budget is exhausted. Repetition of reasoning is not evidence and cannot increase readiness.

## 6. Regression carry-forward

Historical executed evidence may be carried forward only when the baseline source digest is independently checked, all changed evidence-source paths are explicitly allowlisted, forbidden runtime/domain/infrastructure/security prefixes are byte-identical, and a fresh current-source targeted regression suite passes. Carry-forward is an engineering-readiness mechanism only; production gates remain source-exact.

## 7. Negative controls

Claims assigned `EXECUTED_WITH_NEGATIVE_CONTROL` require an executable refusal/destruction/adversarial path in addition to a positive path. Package safety includes destructive traversal, duplicate-name, casefold-alias, symlink/special-file and mode-loss tests. Security and inference claims must preserve fail-closed behavior under malformed or adversarial inputs.

## 8. Scoring

For each dimension:

`raw = passed_criteria / total_criteria`

The raw result is calibrated by the assurance evidence ceiling for the declared evidence class. The release readiness index is the preregistered weighted sum across dimensions. No missing or external predicate is imputed as PASS.

The target predicate is:

`engineering_readiness_percent >= 94.7`

The production predicate is independent:

`production_authorized == true`

The first predicate can be true while the second remains false.

## 9. Non-compensable external boundary

The following remain outside the engineering maturity numerator and cannot be replaced by self-attestation: independent external red-team, live vulnerability scanners, live PostgreSQL/RLS execution, real-domain and independent TEVV, production-like TEVV/load/recovery attestations, trusted hosted build provenance, trusted release signing, and exact CPython 3.12.13 execution.

## 10. Reproducibility and truth

The canonical package must contain a clean source tree, source manifest, distribution manifest, machine evidence index, claim ledger, blocker registry and verification reports. Current-looking evidence with a stale source digest is rejected. The package verifier performs archive-safety validation before extraction and verifies path parity, digests and file modes against the distribution manifest.

## 11. Stop condition

The campaign terminates when one of these conditions holds:

1. the preregistered 94.7 target is met with all included evidence checks passing and no unresolved internal P0 blocker;
2. a new inference cycle changes neither the decision nor the admissible evidence set;
3. a hard inference budget is exhausted;
4. the remaining blockers require an external execution or trust authority unavailable to this runtime.

No criterion may be marked PASS merely to reach the target.
