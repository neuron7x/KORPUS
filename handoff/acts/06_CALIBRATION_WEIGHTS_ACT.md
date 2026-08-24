# Act 06 — calibration, parameters and weights

## Current engineering defaults

| Parameter | Value |
|---|---:|
| BM25 `k1` | 1.50 |
| BM25 `b` | 0.75 |
| lexical weight | 0.42 |
| semantic weight | 0.00 |
| query-coverage weight | 0.24 |
| character similarity | 0.10 |
| authority weight | 0.14 |
| phrase weight | 0.06 |
| temporal weight | 0.04 |
| MMR lambda | 0.82 |
| per-version cap | 2 |
| candidate budget | 256 |
| retrieval timeout | 1200 ms |
| development minimum retrieval score | 0.18 |
| runtime minimum query coverage | 0.25 |
| frozen-eval minimum query coverage | 0.50 |
| development minimum support score | 0.18 |

The seven retrieval weights form a convex combination and sum to exactly 1.00. Semantic weight is intentionally zero until a provider, model, dimensions, dataset, protocol and calibration profile are independently bound and validated.

## Authority priors

`official_ua=1.00`, `official_allied=0.92`, `manufacturer=0.78`, `approved_training=0.74`, `analytical=0.46`, `historical=0.30`, `unknown=0.00`.

These values are explicit profile inputs, not established production truth. Real-corpus calibration must test and may replace them.

## Existing tuning method

`application/tuning.py` performs deterministic simplex/grid search over convex weights and BM25 candidates. Utility is `0.50*nDCG@10 + 0.30*Recall@20 + 0.20*MRR@10`. Production use requires separate train/dev/locked holdout partitions and cannot tune on the holdout.

## Production activation gates

- at least 100 judged ranking queries;
- at least 200 accepted-answer calibration samples;
- `nDCG@10 >= 0.70` and `Recall@20 >= 0.85` as current minimum profile gates;
- finite-sample accepted-answer risk bound below the declared limit;
- zero leakage and citation-integrity failures;
- dataset, protocol, system manifest and model configuration hashes bound to the profile.

Machine-readable registry: `handoff/machine/calibration_weights.json`.
