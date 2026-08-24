# Frozen evaluation

`datasets/frozen.jsonl` is the minimum executable gate. Any retrieval, authorization, extraction, ranking, answer, or provider change must run it unchanged. New failure classes are appended; existing cases are never silently rewritten to make a model pass.

Metrics emitted by `scripts/run_evals.py`:

- answer/abstention status accuracy;
- unauthorized-corpus denial;
- restricted-marker leakage;
- exact case ledger.

A production evaluation set additionally requires domain-expert annotations, temporal-version cases, OCR gold pages, contradiction pairs, citation precision/coverage, and inter-reviewer agreement. Those data are not fabricated in this repository.
