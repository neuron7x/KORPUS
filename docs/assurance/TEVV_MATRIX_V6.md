# TEVV matrix v6

## Layer model

| Layer | Question | Required evidence | Failure meaning |
|---|---|---|---|
| Unit | Does one deterministic rule implement its contract? | pytest predicate | local logic defect |
| Integration | Do repository/API/storage boundaries preserve the contract? | executed integration tests | composition defect |
| Negative control | Would the test fail if the defended invariant were removed? | mutation/destruction/adversarial witness | test may be non-discriminating |
| Metamorphic | Does behavior remain valid under semantics-preserving transformation? | paired/generated cases | hidden coupling/brittleness |
| Noninterference | Does changing unrelated/unauthorized state affect output? | cross-scope canaries | confidentiality/isolation defect |
| Temporal | Does version/effective/revocation state remain coherent over time? | temporal vectors + state tests | stale authority / ABA risk |
| Concurrency | Does the property survive races and transaction interleavings? | concurrent DB/API execution | race condition |
| Recovery | Can service/data return without violating identity/integrity? | executed restore/drill | operational unrecoverability |
| Load/soak | Do bounded-resource properties survive representative pressure? | representative measurements | capacity/reliability limit |
| External | Can an independent actor falsify the security/assurance claims? | signed independent evidence | assurance independence gap |

## Candidate acceptance predicates

1. zero failed functional tests;
2. line/branch coverage above the explicit engineering floor, without treating coverage as authorization;
3. zero surviving critical mutants;
4. deterministic reference evaluation pass rate 1.0 for the approved corpus/version;
5. no citation or leakage failure;
6. migration/schema contract pass;
7. package/source identity pass;
8. new v2 synthetic datasets are byte-bound, unique-ID checked and contain only synthetic canaries;
9. formal reference-model tests pass;
10. non-executed external gates remain visible as blockers.

## Dataset v2

The release evaluation corpus adds 16,500 deterministic synthetic vectors across retrieval attacks, noninterference, temporal authority and package tampering. Every file is SHA-256 bound in `RELEASE_EVAL_DATASET_MANIFEST.json`; every canary is unique within its dataset family. The corpus is designed to make leakage and stale-state defects observable without containing customer data or secrets.
