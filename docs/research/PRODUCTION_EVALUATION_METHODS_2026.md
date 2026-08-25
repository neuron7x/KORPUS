# Production evaluation methods adopted in KORPUS — 2026

Authority boundary: these primary sources inform test design; citation does not prove
that KORPUS satisfies a control. Satisfaction belongs only to current, source-bound
execution evidence and independent attestation where policy requires it.

## OpenAI deployment simulation

Primary source: https://openai.com/index/deployment-simulation/ (2026-06-16).

Adopted invariant: a production TEVV campaign must exercise realistic deployment
context, hide obvious evaluation cues and simulate dependency/tool behavior. A static
benchmark can execute successfully but cannot receive production admission without all
three predicates. Implementation: `CampaignContext` and `_campaign_checks` in
`application/evaluation_validity.py`.

## OpenAI Preparedness Framework

Primary source: https://openai.com/index/updating-our-preparedness-framework/ (2025-04-15).

Adopted invariant: capability evidence and safeguard evidence are separate, defense in
depth is explicit, and residual risk is reviewed rather than averaged into a benchmark.
KORPUS implements conjunctive hard predicates and does not let weighted readiness
authorize production.

## Stanford CRFM HELM

Primary sources: https://crfm.stanford.edu/helm/index.html and
https://crfm.stanford.edu/2024/11/08/helm-safety.html.

Adopted invariant: evaluation is decomposed by scenario, cohort, dimension and metric;
an aggregate score cannot compensate for an uncovered or failed high-consequence slice.
KORPUS records required dimensions/cohorts, hard-failure classes and per-cohort floors.

## NIST AI 600-1

Primary source: https://doi.org/10.6028/NIST.AI.600-1.

Adopted invariant: generative-AI risk is governed, mapped, measured and managed across
the lifecycle. KORPUS therefore binds corpus admission, tested-system identity,
measurement, deployment controls, incident evidence and promotion as distinct stages.
