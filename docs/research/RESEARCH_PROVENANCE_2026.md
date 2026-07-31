# Research provenance and design consequences

Reviewed: 2026-07-31. Sources below are primary research papers or first-party research/engineering publications. Authority is not inherited from institution names; every adopted idea is mapped to an executable design consequence.

## Stanford CRFM — HELM and AIR-Bench

Source: https://crfm.stanford.edu/2022/11/17/helm.html

Adopted consequence:

- evaluate across a taxonomy rather than one accuracy score;
- expose missing scenarios and metrics;
- standardize adaptation and record raw outputs;
- measure robustness, calibration, efficiency and harms in the same deployment context.

KORPUS implementation: risk-tagged frozen cases, separate leakage/citation/determinism metrics, explicit open obligations, reproducible dataset hash.

## Google DeepMind — FACTS, frontier and cyber evaluations

Sources:

- https://deepmind.google/research/evals/
- https://deepmind.google/blog/facts-grounding-a-new-benchmark-for-evaluating-the-factuality-of-large-language-models/
- https://deepmind.google/blog/strengthening-our-frontier-safety-framework/
- https://deepmind.google/blog/evaluating-potential-cybersecurity-threats-of-advanced-ai/

Adopted consequence:

- grounding is evaluated as complete support by supplied documents, not mere citation presence;
- safety gates use explicit capability/risk thresholds and early-warning tests;
- cyber evaluation must cover an end-to-end attack chain, not isolated trivia.

KORPUS implementation: claim-to-span checks, abstention, source/query injection cases, noninterference, attack-oriented mutation tests, named deployment blockers.

## xAI — blind production evaluation and atomic factual claims

Source: https://x.ai/news/grok-4-1

Adopted consequence:

- supplement public benchmarks with blind production-distribution evaluation;
- decompose factuality into atomic claims rather than judge only whole-answer style.

KORPUS implementation: claims are first-class schema objects; production evaluation is designed as a separate corpus-specific gate, not inferred from synthetic fixtures.

## RAGChecker

Paper: https://arxiv.org/abs/2408.08067

Adopted consequence: retrieval and generation failures require separate diagnostics. KORPUS records retrieved count, eligible count, retrieval components, evidence coverage, citation count and decision reason rather than one opaque score.

## ALCE

Paper: https://arxiv.org/abs/2305.14627

Adopted consequence: citation correctness and citation completeness are distinct. KORPUS verifies exact quote binding and measures query-token evidence coverage separately.

## Uncertainty-aware abstention

Paper: https://arxiv.org/abs/2607.04430

Adopted consequence: a threshold is not valid because it “looks reasonable.” Controlled deployment requires a content-addressed calibration profile with sample count, observed failures, confidence level and finite-sample upper error bound.

## Harvard DASlab — self-designing data and RAG systems

Source: https://daslab.seas.harvard.edu/classes/cs265/

Adopted consequence: storage, indexing, retrieval and workload should be co-designed. KORPUS separates database candidate generation from bounded reranking and exposes a candidate budget instead of scanning all accessible spans.

## Harvard adversarial-attack dataset lineage

Source: https://dash.harvard.edu/handle/1/42719210

Adopted consequence: adversarial robustness requires large, evolving attack distributions. The included injection fixtures are mechanism checks only; a real red-team corpus remains an open production obligation.

## Rejected cargo cults

- Copying a frontier laboratory's model stack without its data, compute, threat model and evaluation evidence.
- Treating a leaderboard rank as system assurance.
- Adding agents where a deterministic transaction or state machine is sufficient.
- Replacing corpus governance with a larger context window.
- Calling an uncalibrated similarity score “confidence.”
