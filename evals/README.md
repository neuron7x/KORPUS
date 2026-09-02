# Frozen evaluation

`datasets/assurance.jsonl` is the minimum executable gate: `scripts/run_evals.py:32` reads
exactly that file (`DATASET = Path("evals/datasets/assurance.jsonl")`). Any retrieval,
authorization, extraction, ranking, answer, or provider change must run it unchanged. New
failure classes are appended; existing cases are never silently rewritten to make a model pass.

**ВИПРАВЛЕНО 2026-09-02.** Тут було названо `datasets/frozen.jsonl`. Той файл зобов'язаний
лише ІСНУВАТИ — `korpus/repository_requirements.py:114` перевіряє його наявність, і більше
його не запускає ніщо. Документ називав виконуваним гейтом набір, який не виконується:
читач, що прогнав би «мінімальний гейт» за цим текстом, не прогнав би нічого.

Metrics emitted by `scripts/run_evals.py`:

- answer/abstention status accuracy;
- unauthorized-corpus denial;
- restricted-marker leakage;
- exact case ledger.

A production evaluation set additionally requires domain-expert annotations, temporal-version cases, OCR gold pages, contradiction pairs, citation precision/coverage, and inter-reviewer agreement. Those data are not fabricated in this repository.
